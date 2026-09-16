"""``innereye job`` — collect work that outlives the process that started it.

Generation is slow: video takes minutes, images take seconds to minutes. Agents
call CLIs in loops, so a blocking call that holds a terminal for eight minutes
is a bug. ``innereye render --apply`` returns a handle; this noun group is how
that handle is followed up — from any later process, per the job store's
contract.

Sub-verbs: ``overview`` (what jobs exist), ``status``, ``fetch``, ``cancel``.
Submission lives on ``render`` rather than here — see the module note below.

``--wait`` is the convenience blocking mode for humans. It owns its own timeout
because the CLI core hands a handler no timeout or cancellation plumbing at all,
and it reports progress on **stderr** so stdout carries exactly one payload.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from innereye import jobs
from innereye import provenance as prov
from innereye.backends import _http
from innereye.backends.comfyui import DEFAULT_ENDPOINT, ComfyUIBackend
from innereye.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from innereye.cli._output import emit_diagnostic, emit_result
from innereye.preview import preview as render_preview

_POLL_SECONDS = 1.5

_JSON_HELP = "Emit structured JSON."
_JOB_ID_HELP = "Job id from 'innereye render --apply'."


def _backend(args: argparse.Namespace, record: jobs.JobRecord | None = None) -> ComfyUIBackend:
    """Resolve the backend for a follow-up command.

    The endpoint recorded on the job wins over the CLI default: a render
    submitted to a remote server must be followed up on THAT server, or the
    command silently talks to loopback and either finds nothing or, worse,
    finds an unrelated job that happens to share an id.
    """
    explicit = getattr(args, "endpoint", None)
    if explicit and explicit != DEFAULT_ENDPOINT:
        endpoint = explicit  # an explicit override wins
    elif record is not None and record.endpoint:
        endpoint = record.endpoint  # where the job actually went
    else:
        endpoint = explicit or DEFAULT_ENDPOINT
    return ComfyUIBackend(endpoint, timeout=getattr(args, "timeout", _http.DEFAULT_TIMEOUT))


def _refresh(backend: ComfyUIBackend, record: jobs.JobRecord) -> dict[str, Any]:
    """Ask the backend where the job stands and persist any state change."""
    state = backend.status(record.backend_job_id)
    if state["state"] != record.state:
        record.state = state["state"]
        record.error = state.get("error", "")
        jobs.save(record)
    return state


def wait_for(
    backend: ComfyUIBackend,
    record: jobs.JobRecord,
    *,
    timeout: float = 900.0,
) -> dict[str, Any]:
    """Block until the job reaches a terminal state, reporting progress on stderr.

    Owns its own deadline and its own KeyboardInterrupt handling: ``_dispatch``
    calls a handler exactly once with no cancellation token, so nothing else
    will do it.
    """
    deadline = time.monotonic() + timeout
    last = ""
    try:
        while True:
            state = _refresh(backend, record)
            if state["state"] != last:
                emit_diagnostic(f"job {record.id}: {state['state']}")
                last = state["state"]
            if state["state"] in jobs.TERMINAL_STATES:
                return state
            if state["state"] == jobs.STATE_UNKNOWN:
                # The backend has explicitly said it no longer knows this job.
                # Polling for the remaining timeout cannot change that.
                raise CliError(
                    code=EXIT_ENV_ERROR,
                    message=f"backend no longer knows job {record.id}",
                    remediation=(
                        "the server was probably restarted, which invalidates its queue "
                        "ids; resubmit the render"
                    ),
                )
            if time.monotonic() >= deadline:
                raise CliError(
                    code=EXIT_ENV_ERROR,
                    message=f"job {record.id} did not finish within {timeout:g}s",
                    remediation=f"it may still be running; poll 'innereye job status {record.id}'",
                )
            time.sleep(_POLL_SECONDS)
    except KeyboardInterrupt:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"stopped waiting for job {record.id}",
            remediation=(
                f"the job is still queued; collect with 'innereye job fetch {record.id}' "
                f"or stop it with 'innereye job cancel {record.id}'"
            ),
        ) from None


def collect(
    backend: ComfyUIBackend,
    record: jobs.JobRecord,
    args: argparse.Namespace,
    *,
    json_mode: bool,
) -> int:
    """Download a finished job's artifacts, write provenance, optionally preview."""
    artifacts = backend.fetch(record.backend_job_id, record.output_node)
    out_dir = Path(getattr(args, "out", "renders") or "renders")
    out_dir.mkdir(parents=True, exist_ok=True)
    overwrite = bool(getattr(args, "overwrite", False))

    written: list[dict[str, str]] = []
    resolved = dict(record.resolved or {})
    for filename, data in artifacts:
        # The backend is not trusted with a path. resolve_within rejects
        # absolute, separator-bearing and traversal names, and proves the
        # result sits directly under --out before anything is written.
        target = prov.resolve_within(out_dir, f"{record.id}_{filename}")
        provenance = prov.Provenance(
            backend=record.backend,
            task=record.task,
            seed=int(record.recipe.get("params", {}).get("seed", -1)),
            container=prov.container_for(filename),
            recipe=record.recipe,
            graph_path=record.graph_path,
            graph_digest=str(resolved.get("graph_digest", "")),
            models=list(resolved.get("models", [])),
            sampling=dict(resolved.get("sampling", {})),
            size=dict(resolved.get("size", {})),
            input_digests=dict(record.input_digests or {}),
            endpoint=record.endpoint,
            backend_job_id=record.backend_job_id,
        )
        artifact_path, sidecar_path = prov.write_artifact(
            target, data, provenance, overwrite=overwrite
        )
        written.append({"artifact": str(artifact_path), "provenance": str(sidecar_path)})

        if getattr(args, "preview", False):
            # A preview is a human affordance, not a parseable result, so it
            # goes to stderr in BOTH modes. Writing kitty escape codes to
            # stdout would break the "exactly one payload on stdout" contract
            # under --json -- which is how this was found.
            text, result = render_preview(data, filename)
            if text:
                emit_diagnostic(text)
            emit_diagnostic(f"preview: {result.describe()}")

    record.artifacts = [entry["artifact"] for entry in written]
    jobs.save(record)

    if json_mode:
        emit_result({"job": record.id, "state": record.state, "artifacts": written}, json_mode=True)
    else:
        lines = [f"job {record.id} {record.state}"]
        for entry in written:
            lines.append(f"  artifact:   {entry['artifact']}")
            lines.append(f"  provenance: {entry['provenance']}")
        emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_overview(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    records = list(jobs.iter_jobs())
    payload = {
        "noun": "job",
        "store": str(jobs.store_dir()),
        "schema_version": jobs.SCHEMA_VERSION,
        "verbs": ["overview", "status", "fetch", "cancel"],
        "states": sorted(jobs.STATES),
        "jobs": [
            {"id": r.id, "state": r.state, "task": r.task, "backend": r.backend} for r in records
        ],
    }
    if json_mode:
        emit_result(payload, json_mode=True)
        return 0
    emit_result(_overview_text(records), json_mode=False)
    return 0


def _overview_text(records: list[jobs.JobRecord]) -> str:
    """The human rendering of the job noun's overview."""
    lines = [
        "innereye job — follow up work that outlives the submitting process",
        f"  store:  {jobs.store_dir()} (schema v{jobs.SCHEMA_VERSION})",
        "  verbs:  overview, status, fetch, cancel",
        f"  states: {', '.join(sorted(jobs.STATES))}",
        "",
        f"  {len(records)} job(s):" if records else "  no jobs recorded",
    ]
    for r in records:
        lines.append(f"    {r.id}  {r.state:<12} {r.task}")
    return "\n".join(lines)


def cmd_status(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    record = jobs.load(args.job_id)
    state = _refresh(_backend(args, record), record)
    payload = {
        "job": record.id,
        "backend_job_id": record.backend_job_id,
        "state": state["state"],
        "task": record.task,
        "error": state.get("error", ""),
    }
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        line = f"job {record.id}: {state['state']}"
        if state.get("error"):
            line += f"\n  error: {state['error']}"
        emit_result(line, json_mode=False)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    record = jobs.load(args.job_id)
    backend = _backend(args, record)
    if args.wait:
        wait_for(backend, record, timeout=args.wait_timeout)
    else:
        _refresh(backend, record)
    return collect(backend, record, args, json_mode=json_mode)


def cmd_cancel(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    record = jobs.load(args.job_id)
    backend = _backend(args, record)
    # cancel() raises unless the backend confirmed a TARGETED cancellation, so
    # reaching this line means the requested job really was cancelled.
    backend.cancel(record.backend_job_id)
    record.state = jobs.STATE_CANCELLED
    jobs.save(record)
    if json_mode:
        emit_result({"job": record.id, "state": record.state}, json_mode=True)
    else:
        emit_result(f"job {record.id} cancelled", json_mode=False)
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="ComfyUI endpoint.")
    parser.add_argument(
        "--timeout", type=float, default=_http.DEFAULT_TIMEOUT, help="HTTP timeout."
    )
    # Every level declares its own --json; argparse does not inherit the parent's.
    parser.add_argument("--json", action="store_true", help=_JSON_HELP)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("job", help="Follow up submitted render jobs.")
    p.add_argument("--json", action="store_true", help=_JSON_HELP)
    p.set_defaults(func=cmd_overview, json=False)

    # parser_class=type(p) keeps nested parse errors inside the structured
    # error contract instead of argparse's default stderr/exit 2.
    noun_sub = p.add_subparsers(dest="job_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the job noun and list known jobs.")
    ov.add_argument("--json", action="store_true", help=_JSON_HELP)
    ov.set_defaults(func=cmd_overview)

    st = noun_sub.add_parser("status", help="Report one job's state.")
    st.add_argument("job_id", help=_JOB_ID_HELP)
    _add_common(st)
    st.set_defaults(func=cmd_status)

    fe = noun_sub.add_parser("fetch", help="Download a finished job's artifacts.")
    fe.add_argument("job_id", help=_JOB_ID_HELP)
    fe.add_argument("--out", default="renders", help="Directory for artifacts.")
    fe.add_argument("--preview", action="store_true", help="Show the artifact in the terminal.")
    fe.add_argument("--overwrite", action="store_true", help="Replace an existing artifact.")
    fe.add_argument("--wait", action="store_true", help="Block until the job finishes.")
    fe.add_argument(
        "--wait-timeout",
        dest="wait_timeout",
        type=float,
        default=900.0,
        help="Seconds to wait with --wait (default 900).",
    )
    _add_common(fe)
    fe.set_defaults(func=cmd_fetch)

    ca = noun_sub.add_parser("cancel", help="Stop a queued or running job.")
    ca.add_argument("job_id", help=_JOB_ID_HELP)
    _add_common(ca)
    ca.set_defaults(func=cmd_cancel)
