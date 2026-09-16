"""The portable recipe — ``(task, inputs, params)`` — and how it compiles into a graph.

This module is the **backend-independent layer**. It must never import a
backend, a transport, or anything ComfyUI-shaped: a recipe describes *what* to
generate, and each adapter compiles it into its own native form.

Two ideas carry the design:

* A :class:`Recipe` covers image and video through **one** compile path. Video
  is not a special case — ``fps`` and ``length`` are ordinary params sitting
  beside ``width``, ``height``, ``steps`` and ``seed``.
* A template graph is inert without a :class:`GraphMapping`. Node ids are *not*
  stable across graphs (flux saves at node ``9``, hidream at node ``12``), so a
  graph path alone cannot be compiled. The mapping is part of what the operator
  supplies, and innereye never guesses a node id.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from innereye.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError

# Generation tasks an adapter may declare support for.
TASK_TEXT_TO_IMAGE = "text_to_image"
TASK_IMAGE_TO_IMAGE = "image_to_image"
TASK_TEXT_TO_VIDEO = "text_to_video"
TASK_IMAGE_TO_VIDEO = "image_to_video"
TASK_VIDEO_TO_VIDEO = "video_to_video"
TASK_EMBEDDING_TO_IMAGE = "embedding_to_image"

TASKS = frozenset(
    {
        TASK_TEXT_TO_IMAGE,
        TASK_IMAGE_TO_IMAGE,
        TASK_TEXT_TO_VIDEO,
        TASK_IMAGE_TO_VIDEO,
        TASK_VIDEO_TO_VIDEO,
        TASK_EMBEDDING_TO_IMAGE,
    }
)

# Input modalities. ``embedding`` is first-class by design even though no
# backend supports it yet -- see ``innereye.backends`` for why the refusal
# path is built before the feature.
MODALITY_TEXT = "text"
MODALITY_IMAGE = "image"
MODALITY_EMBEDDING = "embedding"

MODALITIES = frozenset({MODALITY_TEXT, MODALITY_IMAGE, MODALITY_EMBEDDING})

# Which modality each recipe input belongs to.
_INPUT_MODALITY = {
    "prompt": MODALITY_TEXT,
    "negative_prompt": MODALITY_TEXT,
    "image": MODALITY_IMAGE,
    "mask": MODALITY_IMAGE,
    "control_image": MODALITY_IMAGE,
    "embedding": MODALITY_EMBEDDING,
}

# Tasks whose artifact is a moving picture rather than a still.
_VIDEO_TASKS = frozenset({TASK_TEXT_TO_VIDEO, TASK_IMAGE_TO_VIDEO, TASK_VIDEO_TO_VIDEO})


@dataclass(frozen=True)
class Recipe:
    """A backend-independent generation request.

    ``inputs`` holds modality-bearing content (prompt, image, embedding);
    ``params`` holds the knobs (seed, steps, width, height, sampler, fps,
    length). The split matters because capability negotiation is about
    *modalities*, and an adapter refuses on an input it cannot accept -- never
    on a param it can ignore.
    """

    task: str
    inputs: Mapping[str, Any] = field(default_factory=dict)
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.task not in TASKS:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"unknown task {self.task!r}",
                remediation=f"valid tasks: {', '.join(sorted(TASKS))}",
            )
        unknown = sorted(set(self.inputs) - set(_INPUT_MODALITY))
        if unknown:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"unknown recipe input(s): {', '.join(unknown)}",
                remediation=f"valid inputs: {', '.join(sorted(_INPUT_MODALITY))}",
            )

    @property
    def is_video(self) -> bool:
        """True when this recipe's artifact is a video rather than a still."""
        return self.task in _VIDEO_TASKS

    def modalities(self) -> frozenset[str]:
        """The input modalities this recipe actually uses."""
        return frozenset(_INPUT_MODALITY[name] for name in self.inputs)

    def fields(self) -> dict[str, Any]:
        """Flatten to the dotted field names a :class:`GraphMapping` keys on."""
        flat: dict[str, Any] = {}
        for name, value in self.inputs.items():
            flat[f"inputs.{name}"] = value
        for name, value in self.params.items():
            flat[f"params.{name}"] = value
        return flat


@dataclass(frozen=True)
class GraphMapping:
    """Where each recipe field lands in a specific template graph.

    ``fields`` maps a dotted recipe field (``params.seed``) to a node input
    path (``25.inputs.noise_seed``). ``output_node`` names the node whose
    saved result is the artifact -- ``9`` for flux's ``SaveImage``, ``28`` for
    wan's ``SaveAnimatedWEBP``.
    """

    fields: Mapping[str, str | list[str]]
    output_node: str

    def paths_for(self, recipe_field: str) -> list[str]:
        """Every node input this field writes to.

        A field may legitimately land in more than one place: flux's resolution
        is read by both ``EmptySD3LatentImage`` and ``ModelSamplingFlux``, and
        setting only one of them silently mis-shifts the sampler.
        """
        value = self.fields.get(recipe_field)
        if value is None:
            return []
        return [value] if isinstance(value, str) else list(value)


def load_graph(path: Path) -> dict[str, Any]:
    """Read an API-format template graph the operator supplied."""
    raw = _read_json(path, "template graph")
    if not isinstance(raw, dict) or not raw:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{path} is not an API-format ComfyUI graph",
            remediation=(
                "export one from ComfyUI with Save (API Format) -- the UI-format "
                "export is a different shape and will not compile"
            ),
        )
    return raw


def load_mapping(path: Path) -> GraphMapping:
    """Read the recipe-field-to-node-input mapping that accompanies a graph."""
    raw = _read_json(path, "graph mapping")
    if not isinstance(raw, dict) or "fields" not in raw or "output_node" not in raw:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{path} is not a graph mapping",
            remediation=(
                'a mapping looks like {"output_node": "9", "fields": '
                '{"inputs.prompt": "6.inputs.text"}}'
            ),
        )
    return GraphMapping(fields=dict(raw["fields"]), output_node=str(raw["output_node"]))


def default_mapping_path(graph_path: Path) -> Path:
    """Where a graph's mapping lives when ``--mapping`` is not given."""
    return graph_path.with_suffix(graph_path.suffix + ".mapping.json")


def load_pair(
    graph_path: Path, mapping_path: Path | None = None
) -> tuple[dict[str, Any], GraphMapping]:
    """Load the graph and its mapping together — the pair is the unit, not the file.

    Node ids are not stable across graphs, so a graph without its mapping is
    uncompilable. Refusing here, by name, beats failing later with a confusing
    "node 6 not found".
    """
    graph = load_graph(graph_path)
    resolved = mapping_path or default_mapping_path(graph_path)
    if not resolved.exists():
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no graph mapping found at {resolved}",
            remediation=(
                "pass --mapping, or place it beside the graph -- a template graph "
                "alone cannot be compiled because node ids differ per graph"
            ),
        )
    return graph, load_mapping(resolved)


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no such {what}: {path}",
            remediation="check the path",
        ) from exc
    except json.JSONDecodeError as exc:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{path} is not valid JSON: {exc}",
            remediation=f"the {what} must be a JSON file",
        ) from exc
    except OSError as exc:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"cannot read {path}: {exc}",
            remediation="check permissions",
        ) from exc


def compile_recipe(
    recipe: Recipe,
    graph: Mapping[str, Any],
    mapping: GraphMapping,
) -> dict[str, Any]:
    """Return a copy of ``graph`` with every recipe field written into its node.

    The graph is otherwise left **byte-identical**: innereye writes the mapped
    fields and nothing else, so an operator's graph is never rewritten behind
    their back.

    Raises :class:`CliError` when the recipe carries a field the mapping does
    not place. Silently dropping it would mean generating something other than
    what was asked for, which the caller could not detect from the output.
    """
    compiled = copy.deepcopy(dict(graph))
    unmapped: list[str] = []

    for recipe_field, value in recipe.fields().items():
        paths = mapping.paths_for(recipe_field)
        if not paths:
            unmapped.append(recipe_field)
            continue
        for path in paths:
            _set_node_input(compiled, path, value, recipe_field)

    if unmapped:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"graph mapping does not place: {', '.join(sorted(unmapped))}",
            remediation=(
                "add the missing field(s) to the mapping, e.g. "
                '"params.seed": "25.inputs.noise_seed" -- node ids differ per graph, '
                "so innereye will not guess them"
            ),
        )

    if mapping.output_node not in compiled:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"mapping names output node {mapping.output_node!r}, absent from the graph",
            remediation="check the mapping's output_node against the graph's node ids",
        )

    return compiled


def _set_node_input(
    graph: dict[str, Any],
    path: str,
    value: Any,
    recipe_field: str,
) -> None:
    """Write ``value`` at a dotted ``node.inputs.name`` path inside ``graph``."""
    parts = path.split(".")
    if len(parts) < 2:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"mapping for {recipe_field} is not a node path: {path!r}",
            remediation='a node path looks like "6.inputs.text"',
        )

    node_id, rest = parts[0], parts[1:]
    node = graph.get(node_id)
    if node is None:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"mapping for {recipe_field} names node {node_id!r}, absent from the graph",
            remediation=(
                "node ids are not stable across graphs -- check the mapping "
                "belongs to the graph you supplied"
            ),
        )

    cursor: Any = node
    for key in rest[:-1]:
        if not isinstance(cursor, dict) or key not in cursor:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"mapping path {path!r} does not resolve in node {node_id!r}",
                remediation="check the node's input names against the graph",
            )
        cursor = cursor[key]

    if not isinstance(cursor, dict):
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"mapping path {path!r} does not resolve to a node input table",
            remediation="check the node's input names against the graph",
        )
    cursor[rest[-1]] = value
