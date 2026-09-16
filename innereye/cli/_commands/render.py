"""``innereye render`` — turn a prompt into an actual picture or clip.

**Dry-run by default.** Generation spends GPU time and writes files, so a bare
``innereye render`` prints the compiled recipe and the resolved backend and
exits, having submitted nothing. ``--apply`` commits. An agent can therefore
check itself before spending.

**The operator supplies the graph.** innereye ships no default template graph
and never silently picks one — node ids differ per graph, so a graph is only
usable together with its mapping. ``--demo`` is a *separately named mode* that
downloads one of NVIDIA's playbook graphs and writes a matching mapping beside
it; it is the only path in this module that touches the network, and the
ordinary render path never does.

Note the demo graphs need weights to match: ``flux-text-to-image`` wants the
playbook's tier-1 FLUX set (~70 GB). Downloading the graph does not download
the model.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from innereye import jobs
from innereye import provenance as prov
from innereye.backends import _http, negotiate
from innereye.backends.comfyui import (
    DEFAULT_ENDPOINT,
    SERVER_SIDE_COPY_NOTE,
    ComfyUIBackend,
    describe_graph,
    graph_digest,
)
from innereye.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from innereye.cli._output import emit_diagnostic, emit_result
from innereye.recipe import Recipe, compile_recipe, load_pair

# Pinned to an immutable commit, not refs/heads/main. A demo graph is copied
# largely unchanged and then submitted to the operator's server, so tracking a
# moving branch means an upstream change -- or an upstream compromise -- silently
# alters the workload that runs on their GPU.
_PLAYBOOK_COMMIT = "3410c65fbf4bdae2a7c0d8261f83ab665e2e0aa6"
_PLAYBOOK_BASE = (
    "https://raw.githubusercontent.com/NVIDIA/dgx-spark-playbooks/"
    f"{_PLAYBOOK_COMMIT}/nvidia/playbook-comfyui/assets/workflow_api"
)

# Graph name -> (task, mapping). Node ids below were read from the actual
# graphs; they are not guesses, and they differ between the two entries, which
# is exactly why a mapping ships alongside each download.
DEMO_GRAPHS: dict[str, dict[str, Any]] = {
    "flux-text-to-image": {
        "task": "text_to_image",
        "weights": "playbook tier 1 (FLUX.1-dev + text encoders + VAE, ~35 GB)",
        "mapping": {
            "output_node": "9",
            "fields": {
                "inputs.prompt": "6.inputs.text",
                "params.seed": "25.inputs.noise_seed",
                "params.steps": "17.inputs.steps",
                "params.sampler": "16.inputs.sampler_name",
                "params.width": ["27.inputs.width", "30.inputs.width"],
                "params.height": ["27.inputs.height", "30.inputs.height"],
            },
        },
    },
    "wan-text-to-video": {
        "task": "text_to_video",
        "weights": "playbook tier 1 (Wan 2.1 T2V 14B + umt5 encoder + VAE, ~35 GB)",
        "mapping": {
            "output_node": "28",
            "fields": {
                "inputs.prompt": "6.inputs.text",
                "inputs.negative_prompt": "7.inputs.text",
                "params.seed": "3.inputs.seed",
                "params.steps": "3.inputs.steps",
                "params.cfg": "3.inputs.cfg",
                "params.sampler": "3.inputs.sampler_name",
                "params.width": "40.inputs.width",
                "params.height": "40.inputs.height",
                "params.length": "40.inputs.length",
                "params.fps": "28.inputs.fps",
            },
        },
    },
}

_PARAM_FLAGS = ("seed", "steps", "width", "height", "sampler", "cfg", "fps", "length")


def _build_recipe(args: argparse.Namespace) -> Recipe:
    inputs: dict[str, Any] = {}
    if args.prompt:
        inputs["prompt"] = args.prompt
    if args.negative_prompt:
        inputs["negative_prompt"] = args.negative_prompt
    if args.image:
        image_path = Path(args.image)
        try:
            inputs["image"] = image_path.read_bytes()
        except OSError as exc:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"cannot read --image {image_path}: {exc}",
                remediation="check the path",
            ) from exc

    params: dict[str, Any] = {}
    for flag in _PARAM_FLAGS:
        value = getattr(args, flag, None)
        if value is not None:
            params[flag] = value
    params["seed"] = prov.choose_seed(args.seed)

    return Recipe(task=args.task, inputs=inputs, params=params)


def _recipe_summary(recipe: Recipe) -> dict[str, Any]:
    """Recipe rendered for display — image bytes become a length, not a blob.

    This is the *display* form. It is deliberately not what gets persisted:
    a byte count cannot verify or reproduce an image-conditioned render, so
    :func:`_input_digests` carries a sha256 per binary input into provenance.
    """
    shown = {
        key: (f"<{len(value)} bytes>" if isinstance(value, (bytes, bytearray)) else value)
        for key, value in recipe.inputs.items()
    }
    return {"task": recipe.task, "inputs": shown, "params": dict(recipe.params)}


def _input_digests(recipe: Recipe) -> dict[str, str]:
    """sha256 of every binary input, so image-conditioned renders stay verifiable."""
    return {
        key: prov.digest_bytes(bytes(value))
        for key, value in recipe.inputs.items()
        if isinstance(value, (bytes, bytearray))
    }


def _compilable(recipe: Recipe) -> Recipe:
    """A recipe whose binary inputs are stand-in names, for validation only.

    Lets a dry run compile the graph — proving the mapping and output node are
    real — without uploading anything to the server.
    """
    placeheld = {
        key: (f"<{key}>" if isinstance(value, (bytes, bytearray)) else value)
        for key, value in recipe.inputs.items()
    }
    return Recipe(task=recipe.task, inputs=placeheld, params=recipe.params)


def cmd_render(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))

    if args.demo:
        return _fetch_demo(args, json_mode=json_mode)

    if not args.graph:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="--graph is required",
            remediation=(
                "supply an API-format graph exported from ComfyUI with Save (API Format), "
                "plus its mapping; or fetch a demo pair with "
                f"'innereye render --demo {min(DEMO_GRAPHS)}'"
            ),
        )

    graph_path = Path(args.graph)
    mapping_path = Path(args.mapping) if args.mapping else None
    graph, mapping = load_pair(graph_path, mapping_path)

    recipe = _build_recipe(args)
    backend = ComfyUIBackend(args.endpoint, timeout=args.timeout)
    negotiate(recipe, backend)

    if not args.apply:
        # Compile for real, so a malformed mapping or a bad output node fails
        # HERE rather than after --apply has already uploaded images and
        # queued work. Uses placeholder names for binary inputs so nothing is
        # sent to the server.
        preview_graph = compile_recipe(_compilable(recipe), graph, mapping)
        resolved = describe_graph(preview_graph)
        payload = {
            "dry_run": True,
            "resolved": resolved,
            "graph_digest": graph_digest(preview_graph),
            "backend": backend.name,
            "endpoint": backend.endpoint,
            "graph": str(graph_path),
            "output_node": mapping.output_node,
            "recipe": _recipe_summary(recipe),
            "note": "no job submitted; pass --apply to generate",
        }
        if json_mode:
            emit_result(payload, json_mode=True)
        else:
            emit_result(
                "dry run — nothing submitted\n"
                f"  backend: {backend.name} at {backend.endpoint}\n"
                f"  graph:   {graph_path} (output node {mapping.output_node})\n"
                f"  resolved: {json.dumps(resolved)}\n"
                f"  recipe:  {json.dumps(_recipe_summary(recipe), indent=2)}\n"
                "  pass --apply to generate",
                json_mode=False,
            )
        return 0

    digests = _input_digests(recipe)
    compiled = backend.compile(recipe, graph, mapping)
    prov.assert_seed_submitted(compiled, recipe.params["seed"])
    resolved = describe_graph(compiled)
    resolved["graph_digest"] = graph_digest(compiled)
    backend_job_id = backend.submit(compiled)

    record = jobs.record_for(
        backend=backend.name,
        backend_job_id=backend_job_id,
        task=recipe.task,
        output_node=mapping.output_node,
        recipe=_recipe_summary(recipe),
        graph_path=str(graph_path),
        endpoint=backend.endpoint,
        resolved=resolved,
        input_digests=digests,
    )
    jobs.save(record)

    if not args.wait:
        payload = {
            "job": record.id,
            "backend_job_id": backend_job_id,
            "state": record.state,
            "next": f"innereye job fetch {record.id}",
        }
        if json_mode:
            emit_result(payload, json_mode=True)
        else:
            emit_result(
                f"submitted job {record.id}\n  collect with: innereye job fetch {record.id}",
                json_mode=False,
            )
        return 0

    from innereye.cli._commands.job import collect, wait_for

    wait_for(backend, record, timeout=args.wait_timeout)
    return collect(backend, record, args, json_mode=json_mode)


def _fetch_demo(args: argparse.Namespace, *, json_mode: bool) -> int:
    """Download one playbook graph and write its mapping beside it.

    Deliberately a separate mode: the ordinary render path never reaches the
    network, so nobody ends up with a pipeline that silently depends on
    raw.githubusercontent.com being reachable.
    """
    name = args.demo
    entry = DEMO_GRAPHS.get(name)
    if entry is None:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"unknown demo graph {name!r}",
            remediation=f"available: {', '.join(sorted(DEMO_GRAPHS))}",
        )

    into = Path(args.into or ".")
    graph_path = into / f"{name}.api.json"
    mapping_path = Path(str(graph_path) + ".mapping.json")

    if not args.overwrite:
        for existing in (graph_path, mapping_path):
            if existing.exists():
                raise CliError(
                    code=EXIT_USER_ERROR,
                    message=f"refusing to overwrite {existing}",
                    remediation="pass --overwrite, or choose another --into directory",
                )

    url = f"{_PLAYBOOK_BASE}/{name}.api.json"
    emit_diagnostic(f"fetching {url}")
    status, body = _http.get_bytes(url, timeout=args.timeout)
    if status >= 400:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"cannot download the demo graph (HTTP {status})",
            remediation=f"fetch it by hand from {url}",
        )

    try:
        into.mkdir(parents=True, exist_ok=True)
        graph_path.write_bytes(body)
        mapping_path.write_text(json.dumps(entry["mapping"], indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"cannot write the demo pair into {into}: {exc}",
            remediation="check permissions",
        ) from exc

    payload = {
        "graph": str(graph_path),
        "mapping": str(mapping_path),
        "task": entry["task"],
        "weights_required": entry["weights"],
    }
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        emit_result(
            f"demo pair written\n  graph:   {graph_path}\n  mapping: {mapping_path}\n"
            f"  task:    {entry['task']}\n  weights: {entry['weights']}",
            json_mode=False,
        )
    emit_diagnostic("the graph is downloaded; the model weights are not")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "render",
        help="Render an image or video from a prompt (dry-run by default).",
        description=(
            "Compile a recipe into an operator-supplied template graph and submit it "
            "as a job. Dry-run by default; --apply commits. " + SERVER_SIDE_COPY_NOTE
        ),
    )
    p.add_argument("--prompt", help="Positive prompt text.")
    p.add_argument("--negative-prompt", dest="negative_prompt", help="Negative prompt text.")
    p.add_argument("--image", help="Path to an input image (img2img, control, first frame).")
    p.add_argument(
        "--task", default="text_to_image", help="Generation task (default text_to_image)."
    )
    p.add_argument("--graph", help="API-format ComfyUI graph the operator supplies.")
    p.add_argument(
        "--mapping", help="Recipe-field to node-input mapping (default: beside --graph)."
    )
    p.add_argument("--seed", type=int, help="Seed; innereye picks one when omitted.")
    p.add_argument("--steps", type=int, help="Sampler steps.")
    p.add_argument("--cfg", type=float, help="Guidance scale.")
    p.add_argument("--sampler", help="Sampler name.")
    p.add_argument("--width", type=int, help="Output width.")
    p.add_argument("--height", type=int, help="Output height.")
    p.add_argument("--fps", type=int, help="Frames per second (video).")
    p.add_argument("--length", type=int, help="Frame count (video).")
    p.add_argument(
        "--endpoint", default=DEFAULT_ENDPOINT, help="ComfyUI endpoint (loopback default)."
    )
    p.add_argument("--timeout", type=float, default=_http.DEFAULT_TIMEOUT, help="HTTP timeout.")
    p.add_argument("--out", default="renders", help="Directory for artifacts (with --wait).")
    p.add_argument("--apply", action="store_true", help="Actually submit; otherwise dry-run.")
    p.add_argument("--wait", action="store_true", help="Block until the job finishes, then fetch.")
    p.add_argument(
        "--wait-timeout",
        dest="wait_timeout",
        type=float,
        default=900.0,
        help="Seconds to wait with --wait (default 900).",
    )
    p.add_argument("--preview", action="store_true", help="Show the artifact in the terminal.")
    p.add_argument("--overwrite", action="store_true", help="Replace an existing artifact.")
    p.add_argument("--demo", help="Download a named demo graph+mapping instead of rendering.")
    p.add_argument("--into", help="Directory for --demo output (default: current directory).")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_render, json=False)
