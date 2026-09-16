"""Provenance is output, not a log line — plus the collision safety it depends on.

A result that cannot be reproduced cannot be reviewed. So alongside every
artifact innereye writes a sidecar recording the backend, model, **seed**,
resolution, sampler, steps, container and the full recipe.

Two things this module is careful about:

**The seed is innereye's to choose.** :func:`choose_seed` picks one *before*
submission so it can be written into the graph and asserted present in the
submitted payload. A seed read back from a backend's response is not provenance
— it is a report, and a backend that silently ignored it would be
indistinguishable from one that honoured it.

**Predictable paths are destructive paths.** "Artifacts land at predictable
paths" plus "record the seed" means re-running the same recipe with the same
seed resolves to the same filename — silently overwriting the earlier artifact
*and its sidecar*, destroying exactly the evidence the reproducibility claim
depends on. So every write here refuses to clobber unless an explicit
``overwrite`` is passed.

One behaviour worth knowing when sharing results: ComfyUI already embeds the
full prompt graph in what it saves — PNG text chunks for stills, EXIF for
animated WebP. Artifacts are therefore **self-disclosing**: posting a render
posts its prompt and its whole graph. The sidecar is innereye's canonical,
readable copy; it is not the only one.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from innereye.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError

# ComfyUI's samplers take a 64-bit seed; keep well inside it.
_SEED_MAX = 2**63 - 1

# Container by artifact extension. The video graphs innereye drives end in
# SaveAnimatedWEBP, so .webp is the *video* container here -- which is exactly
# why the container is recorded explicitly rather than inferred downstream.
_CONTAINERS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
    ".mp4": "mp4",
    ".gif": "gif",
}

SIDECAR_SUFFIX = ".json"


@dataclass
class Provenance:
    """Everything needed to re-run, diff or review a result."""

    backend: str
    task: str
    seed: int
    container: str
    recipe: dict[str, Any] = field(default_factory=dict)
    graph_path: str = ""
    # A graph *path* is mutable and machine-local; the digest identifies the
    # exact graph that ran even after the file moves or changes.
    graph_digest: str = ""
    # Effective settings read back out of the compiled graph, so a render that
    # relied on graph defaults still records what it actually used rather than
    # leaving nulls beside a 1024x1024 image.
    models: list[str] = field(default_factory=list)
    sampling: dict[str, Any] = field(default_factory=dict)
    size: dict[str, Any] = field(default_factory=dict)
    # sha256 of every binary input, so an image-conditioned render can be
    # verified even though the bytes are not copied into the sidecar.
    input_digests: dict[str, str] = field(default_factory=dict)
    endpoint: str = ""
    backend_job_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def choose_seed(explicit: int | None = None) -> int:
    """Return the seed innereye will write into the graph.

    Never let a backend's random default go unrecorded: when the caller gives
    no seed we pick one here, so the value in the sidecar is the value that was
    submitted.
    """
    if explicit is not None:
        if not isinstance(explicit, int) or isinstance(explicit, bool) or explicit < 0:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"seed must be a non-negative integer, got {explicit!r}",
                remediation="pass --seed with a non-negative integer, or omit it",
            )
        return explicit
    return secrets.randbelow(_SEED_MAX)


def assert_seed_submitted(payload: Any, seed: int) -> None:
    """Prove the chosen seed really is in the payload about to be submitted.

    This is the honesty condition behind the reproducibility claim: a seed that
    only appears in the sidecar tells you nothing about what was generated.
    """
    if not _contains_value(payload, seed):
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"seed {seed} is not present in the compiled graph",
            remediation=(
                "the graph mapping does not place params.seed -- add it, e.g. "
                '"params.seed": "25.inputs.noise_seed"'
            ),
        )


def safe_artifact_name(filename: str) -> str:
    """Reduce a backend-supplied filename to a safe, simple basename.

    The backend is not trusted with a path. A remote or compromised ComfyUI can
    return ``../../outside.png`` or an absolute path, and the caller asked for
    the artifact to land under ``--out`` -- so anything with a separator, a
    traversal component, or a drive/UNC prefix is refused rather than
    normalised into something that looks fine.
    """
    raw = (filename or "").strip()
    if not raw:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message="backend returned an artifact with no filename",
            remediation="the backend response is malformed; nothing was written",
        )
    if "/" in raw or "\\" in raw or "\x00" in raw or ntpath.splitdrive(raw)[0]:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"refusing backend filename containing a path: {raw!r}",
            remediation="innereye writes artifacts only directly under --out",
        )
    if raw in {".", ".."} or raw.startswith(".."):
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"refusing traversal-shaped backend filename: {raw!r}",
            remediation="innereye writes artifacts only directly under --out",
        )
    return raw


def resolve_within(out_dir: Path, name: str) -> Path:
    """Join ``name`` under ``out_dir`` and prove the result stays inside it."""
    root = out_dir.resolve()
    target = (root / safe_artifact_name(name)).resolve()
    if target.parent != root:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"artifact path {target} escapes the output directory {root}",
            remediation="nothing was written",
        )
    return target


def digest_bytes(data: bytes) -> str:
    """sha256 of a binary input, recorded so the input can be verified later."""
    return hashlib.sha256(data).hexdigest()


def container_for(filename: str) -> str:
    """The recorded container for an artifact filename."""
    return _CONTAINERS.get(Path(filename).suffix.lower(), "unknown")


def sidecar_path(artifact: Path) -> Path:
    """Where the provenance JSON for ``artifact`` lives."""
    return artifact.with_suffix(artifact.suffix + SIDECAR_SUFFIX)


def write_artifact(
    path: Path,
    data: bytes,
    provenance: Provenance,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Write an artifact and its sidecar together, refusing to clobber either.

    Both paths are checked *before* either is written, so a refusal never
    leaves an artifact without its provenance.
    """
    sidecar = sidecar_path(path)

    if not overwrite:
        _refuse_if_present(path, sidecar)

    # Stage both, then move both into place. Writing the artifact first and the
    # sidecar second leaves a window where a disk-full or I/O error yields an
    # artifact with no provenance -- and under overwrite, replaces a good
    # artifact while leaving its sidecar stale. An artifact whose provenance is
    # missing is exactly the thing this module exists to prevent.
    payload = json.dumps(provenance.to_dict(), indent=2, sort_keys=True) + "\n"
    tmp_artifact = tmp_sidecar = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_artifact = _stage(path.parent, path.name, data)
        tmp_sidecar = _stage(path.parent, sidecar.name, payload)
        os.replace(tmp_sidecar, sidecar)
        tmp_sidecar = None
        os.replace(tmp_artifact, path)
        tmp_artifact = None
    except OSError as exc:
        for leftover in (tmp_artifact, tmp_sidecar):
            if leftover:
                try:
                    os.unlink(leftover)
                except OSError:
                    pass
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"cannot write artifact to {path}: {exc}",
            remediation=f"check permissions and free space on {path.parent}",
        ) from exc

    return path, sidecar


def _refuse_if_present(*paths: Path) -> None:
    """Refuse before writing anything if any target already exists."""
    for existing in paths:
        if existing.exists():
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"refusing to overwrite {existing}",
                remediation=(
                    "pass --overwrite to replace it, or change the seed or output "
                    "directory -- overwriting would destroy the earlier result's provenance"
                ),
            )


def _stage(directory: Path, name: str, write) -> str:
    """Write via a temp file in ``directory``; return its path for os.replace."""
    fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=f".{name}.")
    with os.fdopen(
        fd,
        "wb" if isinstance(write, bytes) else "w",
        **({} if isinstance(write, bytes) else {"encoding": "utf-8"}),
    ) as stream:
        stream.write(write)
        stream.flush()
        os.fsync(stream.fileno())
    return tmp


def read_sidecar(artifact: Path) -> dict[str, Any]:
    """Read an artifact's provenance back, for a reproduction run."""
    path = sidecar_path(artifact)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no provenance sidecar beside {artifact}",
            remediation=f"expected {path}",
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"provenance sidecar {path} is unreadable: {exc}",
            remediation="the sidecar is corrupt; the artifact cannot be reproduced from it",
        ) from exc


def _contains_value(node: Any, needle: Any) -> bool:
    """Depth-first search for ``needle`` anywhere in a nested JSON-ish structure."""
    if node == needle and isinstance(node, type(needle)):
        return True
    if isinstance(node, dict):
        return any(_contains_value(value, needle) for value in node.values())
    if isinstance(node, (list, tuple)):
        return any(_contains_value(value, needle) for value in node)
    return False
