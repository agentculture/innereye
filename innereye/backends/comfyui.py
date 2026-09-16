"""The ComfyUI adapter — first backend, deliberately not the architecture.

ComfyUI is first because it is local, free, and already supports text and image
inputs. Everything here goes through :mod:`innereye.backends._http`, and every
response shape below was **verified live** against ComfyUI 0.33.2 on
``127.0.0.1:8188`` rather than inferred from its source.

Three decisions worth reading before editing:

**The jobs API, not history polling.** ComfyUI 0.33.2 exposes a first-class
``/api/jobs`` surface whose status enum is ``pending, in_progress, completed,
failed, cancelled``. ``/history`` alone cannot distinguish queued from running
from failed — it returns nothing until a job finishes. So the adapter targets
``/api/jobs`` and falls back to ``/history`` only when that endpoint is absent,
which keeps older servers working without pretending they are equivalent.

**Never pre-flight the weights.** It is tempting to ``GET /object_info`` and
check every loader's named file before submitting. Don't: ComfyUI already fails
closed at submit with ``prompt_outputs_failed_validation`` and a per-node
``node_errors`` payload naming the input, the received value and the full list
of valid values — a better error than a client could construct. The adapter's
job is to *surface* that, not duplicate it.

**Nothing touches the local filesystem.** Artifacts come back over ``/view`` and
the model list over the API, never by reading ComfyUI's ``output/`` or
``models/`` directories. That is what lets the same adapter drive a server on
another host — which the playbook's own ``--listen 0.0.0.0`` exists to allow.

A note the operator deserves: ComfyUI keeps its *own* copy of every artifact
under its output directory, named by an auto-incrementing counter, and innereye
never cleans it. See :data:`SERVER_SIDE_COPY_NOTE`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping, Sequence

from innereye.backends import Capability, _http, register_capability
from innereye.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from innereye.jobs import (
    STATE_CANCELLED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_IN_PROGRESS,
    STATE_PENDING,
    STATE_UNKNOWN,
)
from innereye.recipe import (
    MODALITY_IMAGE,
    MODALITY_TEXT,
    TASK_IMAGE_TO_IMAGE,
    TASK_IMAGE_TO_VIDEO,
    TASK_TEXT_TO_IMAGE,
    TASK_TEXT_TO_VIDEO,
    GraphMapping,
    Recipe,
    compile_recipe,
)

BACKEND_NAME = "comfyui"

# Loopback by default. ComfyUI ships no authentication of any kind, so binding
# anything else exposes the GPU and every prior prompt to the network -- the
# endpoint is configuration, never a constant pointing somewhere remote.
DEFAULT_ENDPOINT = "http://127.0.0.1:8188"

SERVER_SIDE_COPY_NOTE = (
    "ComfyUI also keeps its own copy of every artifact under its output directory, "
    "named by an auto-incrementing counter. innereye does not clean that up."
)

# ComfyUI's own enum, verified live: an invalid ?status= filter makes the
# server enumerate exactly these.
_STATE_MAP = {
    "pending": STATE_PENDING,
    "in_progress": STATE_IN_PROGRESS,
    "completed": STATE_COMPLETED,
    "failed": STATE_FAILED,
    "cancelled": STATE_CANCELLED,
}

# Keys ComfyUI uses inside a node's outputs for saved media.
#
# Verified live: SaveAnimatedWEBP reports its .webp under "images" -- the same
# key SaveImage uses -- and ALSO emits "animated": [true], which is a boolean
# FLAG, not a media list. Treating "animated" as media crashes on the bool.
# Any non-dict entry is skipped for the same reason.
_MEDIA_KEYS = ("images", "gifs", "videos")

CAPABILITY = Capability(
    tasks=frozenset(
        {
            TASK_TEXT_TO_IMAGE,
            TASK_IMAGE_TO_IMAGE,
            TASK_TEXT_TO_VIDEO,
            TASK_IMAGE_TO_VIDEO,
        }
    ),
    # No embedding: ComfyUI can be driven with raw CONDITIONING, but no graph
    # innereye ships exposes it. And no video_to_video -- Recipe has no video
    # input modality and the CLI has no way to supply a source clip, so a
    # caller could pass negotiation and still be unable to express the request.
    # Declaring either would be exactly the lie the negotiation layer exists to
    # catch, and a capability that cannot be exercised is worse than an absent
    # one because it fails late instead of at the boundary.
    modalities=frozenset({MODALITY_TEXT, MODALITY_IMAGE}),
)

register_capability(BACKEND_NAME, CAPABILITY)


# Node inputs that name a model file, by convention across ComfyUI loaders.
_MODEL_INPUTS = (
    "unet_name",
    "ckpt_name",
    "model_name",
    "vae_name",
    "clip_name",
    "clip_name1",
    "clip_name2",
)
# Node inputs that describe how sampling actually ran.
_SAMPLER_INPUTS = ("sampler_name", "scheduler", "steps", "cfg", "denoise")
_SIZE_INPUTS = ("width", "height", "length", "fps")


def describe_graph(compiled: Mapping[str, Any]) -> dict[str, Any]:
    """Read the settings a compiled graph will actually run with.

    Provenance that only records what the *caller* passed is incomplete: a
    render that relies on the template graph's defaults ends up with a sidecar
    saying ``width: null`` beside a 1024x1024 image. This reads the effective
    values back out of the graph after compilation, so the sidecar describes
    the artifact rather than the command line.
    """
    found: dict[str, Any] = {"models": [], "sampling": {}, "size": {}}
    for node in compiled.values():
        for key, value in _literal_inputs(node):
            _classify_input(key, value, found)
    return found


def _literal_inputs(node: Any) -> list[tuple[str, Any]]:
    """The literal (non-wired) inputs of one node.

    A list value is a wire to another node, not a setting, so it is skipped.
    """
    if not isinstance(node, dict):
        return []
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        return []
    return [(k, v) for k, v in inputs.items() if not isinstance(v, list)]


def _classify_input(key: str, value: Any, found: dict[str, Any]) -> None:
    """File one literal input under models / sampling / size, first wins."""
    if key in _MODEL_INPUTS and isinstance(value, str):
        if value not in found["models"]:
            found["models"].append(value)
    elif key in _SAMPLER_INPUTS:
        found["sampling"].setdefault(key, value)
    elif key in _SIZE_INPUTS:
        found["size"].setdefault(key, value)


def graph_digest(compiled: Mapping[str, Any]) -> str:
    """A stable sha256 over the exact graph submitted.

    A graph *path* is mutable and machine-local; a digest identifies the graph
    that actually ran even after the file moves or changes.
    """
    canonical = json.dumps(compiled, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class ComfyUIBackend:
    """Drives a ComfyUI server over HTTP. It drives ComfyUI; it does not become it."""

    name = BACKEND_NAME

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        timeout: float = _http.DEFAULT_TIMEOUT,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._jobs_api: bool | None = None

    # -- declaration ----------------------------------------------------

    def capability(self) -> Capability:
        return CAPABILITY

    # -- compile --------------------------------------------------------

    def compile(
        self,
        recipe: Recipe,
        graph: Mapping[str, Any],
        mapping: GraphMapping,
    ) -> dict[str, Any]:
        """Fill the template graph's input nodes from the recipe.

        Image inputs are uploaded first: ComfyUI's ``LoadImage`` takes a
        server-side *filename*, not bytes, so the recipe's image content is
        replaced by the name the server hands back.
        """
        resolved = dict(recipe.inputs)
        for field in ("image", "mask", "control_image"):
            value = resolved.get(field)
            if isinstance(value, (bytes, bytearray)):
                # A per-upload unique name. A fixed "innereye_<field>.png" plus
                # overwrite=true means a later render replaces the bytes an
                # earlier queued job still refers to, and that job then renders
                # someone else's image -- silently, since LoadImage resolves the
                # name at execution time, not at submit time.
                unique = f"innereye_{field}_{uuid.uuid4().hex[:12]}.png"
                resolved[field] = self.upload_image(unique, bytes(value))
        prepared = Recipe(task=recipe.task, inputs=resolved, params=recipe.params)
        return compile_recipe(prepared, graph, mapping)

    def upload_image(self, filename: str, content: bytes) -> str:
        """POST an image and return the server-side name ``LoadImage`` consumes."""
        status, payload = _http.post_multipart(
            f"{self.endpoint}/upload/image",
            filename=filename,
            content=content,
            fields={"overwrite": "true"},
            timeout=self.timeout,
        )
        if status >= 400 or not isinstance(payload, dict) or "name" not in payload:
            raise CliError(
                code=EXIT_ENV_ERROR,
                message=f"ComfyUI rejected the image upload (HTTP {status})",
                remediation=f"response: {str(payload)[:200]}",
            )
        return str(payload["name"])

    # -- submit ---------------------------------------------------------

    def submit(self, payload: Mapping[str, Any]) -> str:
        """Enqueue a compiled graph; return ComfyUI's ``prompt_id``."""
        status, body = _http.post_json(
            f"{self.endpoint}/prompt", {"prompt": dict(payload)}, timeout=self.timeout
        )
        if status >= 400 or (isinstance(body, dict) and body.get("error")):
            raise _validation_error(body, status)
        if not isinstance(body, dict) or "prompt_id" not in body:
            raise CliError(
                code=EXIT_ENV_ERROR,
                message="ComfyUI accepted the prompt but returned no prompt_id",
                remediation=f"response: {str(body)[:200]}",
            )
        return str(body["prompt_id"])

    # -- status ---------------------------------------------------------

    def has_jobs_api(self) -> bool:
        """Whether this server exposes ``/api/jobs`` (cached per adapter)."""
        if self._jobs_api is None:
            status, _ = _http.get_json(f"{self.endpoint}/api/jobs", timeout=self.timeout)
            self._jobs_api = status < 400
        return self._jobs_api

    def status(self, job_id: str) -> dict[str, Any]:
        """Return ``{"state", "outputs", "error"}`` for a submitted job."""
        if self.has_jobs_api():
            code, payload = _http.get_json(
                f"{self.endpoint}/api/jobs/{job_id}", timeout=self.timeout
            )
            if code < 400 and isinstance(payload, dict):
                return _from_jobs_api(payload)
            if code == 404:
                return {"state": STATE_UNKNOWN, "outputs": {}, "error": ""}

        return self._status_via_history(job_id)

    def _status_via_history(self, job_id: str) -> dict[str, Any]:
        """Fallback for servers without ``/api/jobs``.

        Honest about its limits: ``/history`` is empty both for a job that is
        still queued and for one the server has forgotten, so this path cannot
        distinguish them. It reports ``pending`` only when the job is visible in
        the queue, and ``unknown`` otherwise.
        """
        code, payload = _http.get_json(f"{self.endpoint}/history/{job_id}", timeout=self.timeout)
        if code < 400 and isinstance(payload, dict) and job_id in payload:
            record = payload[job_id]
            execution = record.get("status") or {}
            succeeded = execution.get("status_str") == "success"
            return {
                "state": STATE_COMPLETED if succeeded else STATE_FAILED,
                "outputs": record.get("outputs") or {},
                "error": "" if succeeded else _messages_to_text(execution),
            }

        qcode, queue = _http.get_json(f"{self.endpoint}/queue", timeout=self.timeout)
        queued = _queue_state(queue, job_id) if qcode < 400 else None
        return {"state": queued or STATE_UNKNOWN, "outputs": {}, "error": ""}

    # -- fetch ----------------------------------------------------------

    def fetch(self, job_id: str, output_node: str) -> Sequence[tuple[str, bytes]]:
        """Download a completed job's artifacts as ``(filename, bytes)`` pairs."""
        state = self.status(job_id)

        if state["state"] == STATE_FAILED:
            raise CliError(
                code=EXIT_ENV_ERROR,
                message=f"ComfyUI job {job_id} failed",
                remediation=state.get("error") or "check the ComfyUI server log",
            )
        if state["state"] != STATE_COMPLETED:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"job {job_id} is {state['state']}, not completed",
                remediation="poll 'innereye job status' until it reports completed",
            )

        node_outputs = (state.get("outputs") or {}).get(output_node)
        if not node_outputs:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"job {job_id} produced no output at node {output_node}",
                remediation="check the mapping's output_node matches the graph's save node",
            )

        artifacts = [self._download(item) for item in _media_items(node_outputs)]
        if not artifacts:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"node {output_node} reported no downloadable media",
                remediation=f"saw keys: {', '.join(sorted(node_outputs)) or '(none)'}",
            )
        return artifacts

    def _download(self, item: Mapping[str, Any]) -> tuple[str, bytes]:
        filename = str(item.get("filename", ""))
        params = {
            "filename": filename,
            "subfolder": str(item.get("subfolder", "")),
            "type": str(item.get("type", "output")),
        }
        code, body = _http.get_bytes(f"{self.endpoint}/view", params=params, timeout=self.timeout)
        if code >= 400:
            raise CliError(
                code=EXIT_ENV_ERROR,
                message=f"cannot download {filename} from ComfyUI (HTTP {code})",
                remediation="the server may have been restarted since the job completed",
            )
        return filename, body

    # -- cancel ---------------------------------------------------------

    def cancel(self, job_id: str) -> None:
        """Stop a queued or running job — targeted, or not at all.

        ``/interrupt`` is **global**: it stops whatever is currently executing,
        which is not necessarily the job asked about. Falling back to it when a
        targeted cancel fails would stop an unrelated render while leaving the
        requested job running, so it is not a fallback here. A server without
        the jobs API gets an honest refusal instead.
        """
        if not self.has_jobs_api():
            raise CliError(
                code=EXIT_ENV_ERROR,
                message=f"this ComfyUI has no /api/jobs, so job {job_id} cannot be cancelled by id",
                remediation=(
                    "upgrade ComfyUI, or stop the current job from its web UI -- "
                    "innereye will not call the global /interrupt, which would stop "
                    "whatever is running rather than this job"
                ),
            )
        code, body = _http.post_json(
            f"{self.endpoint}/api/jobs/{job_id}/cancel", {}, timeout=self.timeout
        )
        if code >= 400:
            raise CliError(
                code=EXIT_ENV_ERROR,
                message=f"ComfyUI refused to cancel job {job_id} (HTTP {code})",
                remediation=f"it may already have finished; server said: {str(body)[:200]}",
            )


def _queue_state(queue: Any, job_id: str) -> str | None:
    """Whether ``job_id`` is visible in the server's queue, and how."""
    if not isinstance(queue, dict):
        return None
    for key, state in (("queue_running", STATE_IN_PROGRESS), ("queue_pending", STATE_PENDING)):
        for entry in queue.get(key) or []:
            if job_id in str(entry):
                return state
    return None


def _media_items(node_outputs: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The downloadable entries in one node's outputs.

    Skips non-dict entries: SaveAnimatedWEBP reports its .webp under "images"
    but also emits ``"animated": [true]``, a boolean flag that is not media.
    """
    items: list[Mapping[str, Any]] = []
    for key in _MEDIA_KEYS:
        for item in node_outputs.get(key) or []:
            if isinstance(item, dict) and "filename" in item:
                items.append(item)
    return items


def _from_jobs_api(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = str(payload.get("status", "")).lower()
    state = _STATE_MAP.get(raw, STATE_UNKNOWN)
    execution = payload.get("execution_status") or {}
    error = "" if state != STATE_FAILED else _messages_to_text(execution)
    return {"state": state, "outputs": payload.get("outputs") or {}, "error": error}


def _messages_to_text(execution: Mapping[str, Any]) -> str:
    """Flatten ComfyUI's execution messages into one remediation line."""
    parts: list[str] = []
    for message in execution.get("messages") or []:
        if isinstance(message, (list, tuple)) and len(message) >= 2:
            kind, detail = message[0], message[1]
            if "error" in str(kind).lower():
                parts.append(f"{kind}: {str(detail)[:300]}")
    return " | ".join(parts) or str(execution.get("status_str", ""))


def _validation_error(body: Any, status: int) -> CliError:
    """Turn ComfyUI's own validation payload into an actionable CliError.

    This is the whole reason no client-side ``/object_info`` pre-flight exists:
    the server names the node, the input, the value it got and the values it
    would accept. Reconstructing that client-side would be strictly worse.
    """
    if not isinstance(body, dict):
        return CliError(
            code=EXIT_ENV_ERROR,
            message=f"ComfyUI rejected the prompt (HTTP {status})",
            remediation=str(body)[:300],
        )

    error = body.get("error") or {}
    headline = str(error.get("message") or f"ComfyUI rejected the prompt (HTTP {status})")

    details: list[str] = []
    for node_id, node_error in (body.get("node_errors") or {}).items():
        class_type = node_error.get("class_type", "?")
        for item in node_error.get("errors") or []:
            detail = str(item.get("details", "")).strip()
            details.append(f"node {node_id} ({class_type}): {detail or item.get('message', '')}")

    if details:
        remediation = "; ".join(details)
    else:
        remediation = str(error.get("details") or "check the graph against the server's nodes")

    return CliError(code=EXIT_USER_ERROR, message=headline, remediation=remediation)
