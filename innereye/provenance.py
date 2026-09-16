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

import json
import secrets
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
    model: str = ""
    sampler: str = ""
    steps: int | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    length: int | None = None
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
        for existing in (path, sidecar):
            if existing.exists():
                raise CliError(
                    code=EXIT_USER_ERROR,
                    message=f"refusing to overwrite {existing}",
                    remediation=(
                        "pass --overwrite to replace it, or change the seed or output "
                        "directory -- overwriting would destroy the earlier result's provenance"
                    ),
                )

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        sidecar.write_text(
            json.dumps(provenance.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"cannot write artifact to {path}: {exc}",
            remediation=f"check permissions on {path.parent}",
        ) from exc

    return path, sidecar


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
