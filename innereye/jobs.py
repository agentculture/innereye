"""The job store: generation is slow, so it is modelled as jobs that outlive a process.

Video takes minutes and images take seconds to minutes. Agents call CLIs in
loops, so a blocking call that holds a terminal for eight minutes is a bug. An
agent that submits in one invocation must be able to collect in another — which
makes this store **shared mutable state**, and that has consequences the design
answers explicitly:

* **Where it lives** is declared, not implied: ``$INNEREYE_JOB_STORE`` when set,
  otherwise ``$XDG_STATE_HOME/innereye/jobs``, otherwise
  ``~/.local/state/innereye/jobs``. Tests point the env var at a tmp dir, which
  is also what makes the store safe under ``pytest -n auto``.
* **One file per job**, written atomically via a temp file plus ``os.replace``.
  Two concurrent submits touch two different files, so there is no shared
  writer to serialise and no lock to deadlock on.
* **A schema version from the first release.** This is innereye's first on-disk
  format; without a version field the *next* change inherits a migration
  problem with no way to detect which format it is reading. Loading a record
  from a newer schema fails closed rather than guessing.

The backend's own queue is a *second* store that can disagree with this one —
restart ComfyUI and every ``prompt_id`` it held becomes meaningless. That is
what :data:`STATE_UNKNOWN` is for: a job the backend no longer recognises is a
distinct, reportable state, not a hang and not a crash.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from innereye.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError

SCHEMA_VERSION = 1

# Job states. The first five mirror ComfyUI 0.33.2's own enum (verified live:
# an invalid status filter makes the server enumerate them). STATE_UNKNOWN is
# innereye's own -- it describes a record this store holds that the backend no
# longer knows about.
STATE_PENDING = "pending"
STATE_IN_PROGRESS = "in_progress"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"
STATE_UNKNOWN = "unknown"

STATES = frozenset(
    {
        STATE_PENDING,
        STATE_IN_PROGRESS,
        STATE_COMPLETED,
        STATE_FAILED,
        STATE_CANCELLED,
        STATE_UNKNOWN,
    }
)

TERMINAL_STATES = frozenset({STATE_COMPLETED, STATE_FAILED, STATE_CANCELLED})

_ENV_STORE = "INNEREYE_JOB_STORE"


def store_dir() -> Path:
    """The directory holding one JSON file per job."""
    override = os.environ.get(_ENV_STORE)
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "innereye" / "jobs"


@dataclass
class JobRecord:
    """One submitted generation job, as innereye remembers it."""

    id: str
    backend: str
    backend_job_id: str
    state: str
    task: str
    output_node: str
    created_at: float
    schema_version: int = SCHEMA_VERSION
    recipe: dict[str, Any] = field(default_factory=dict)
    graph_path: str = ""
    artifacts: list[str] = field(default_factory=list)
    error: str = ""

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


def new_job_id() -> str:
    """A job id innereye owns, independent of whatever the backend calls it."""
    return uuid.uuid4().hex[:12]


def _path_for(job_id: str) -> Path:
    return store_dir() / f"{job_id}.json"


def save(record: JobRecord) -> Path:
    """Write ``record`` atomically. Safe against concurrent writers by construction."""
    if record.state not in STATES:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"unknown job state {record.state!r}",
            remediation=f"valid states: {', '.join(sorted(STATES))}",
        )

    directory = store_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"cannot create the job store at {directory}: {exc}",
            remediation=f"set {_ENV_STORE} to a writable directory",
        ) from exc

    target = _path_for(record.id)
    payload = json.dumps(asdict(record), indent=2, sort_keys=True)

    # Temp file in the same directory, then os.replace -- an atomic rename on
    # POSIX, so a killed process never leaves a half-written record.
    handle, tmp_name = tempfile.mkstemp(dir=str(directory), prefix=f".{record.id}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, target)
    except OSError as exc:
        _unlink_quietly(tmp_name)
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"cannot write job {record.id} to {target}: {exc}",
            remediation=f"check permissions on {directory}",
        ) from exc
    return target


def load(job_id: str) -> JobRecord:
    """Read one job record back, from any process."""
    path = _path_for(job_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no such job: {job_id}",
            remediation="list known jobs with 'innereye job overview'",
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"job record {path} is unreadable: {exc}",
            remediation="the record is corrupt; delete it and resubmit",
        ) from exc
    return _from_dict(raw, path)


def iter_jobs() -> Iterator[JobRecord]:
    """Yield every readable job record, newest first. Corrupt records are skipped."""
    directory = store_dir()
    if not directory.is_dir():
        return
    records: list[JobRecord] = []
    for path in directory.glob("*.json"):
        try:
            records.append(_from_dict(json.loads(path.read_text(encoding="utf-8")), path))
        except (OSError, json.JSONDecodeError, CliError):
            continue
    yield from sorted(records, key=lambda r: r.created_at, reverse=True)


def record_for(
    *,
    backend: str,
    backend_job_id: str,
    task: str,
    output_node: str,
    recipe: dict[str, Any] | None = None,
    graph_path: str = "",
) -> JobRecord:
    """Build a fresh, pending record for a just-submitted job."""
    return JobRecord(
        id=new_job_id(),
        backend=backend,
        backend_job_id=backend_job_id,
        state=STATE_PENDING,
        task=task,
        output_node=output_node,
        created_at=time.time(),
        recipe=recipe or {},
        graph_path=graph_path,
    )


def _from_dict(raw: dict[str, Any], path: Path) -> JobRecord:
    version = raw.get("schema_version")
    if not isinstance(version, int):
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"job record {path} has no schema_version",
            remediation="the record predates the versioned store; delete it and resubmit",
        )
    if version > SCHEMA_VERSION:
        # Fail closed: a newer innereye wrote this and we cannot know what
        # changed. Guessing is how a store quietly corrupts itself.
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=(
                f"job record {path} uses schema v{version}, "
                f"but this innereye understands v{SCHEMA_VERSION}"
            ),
            remediation="upgrade innereye to read this job store",
        )
    known = {f: raw[f] for f in JobRecord.__dataclass_fields__ if f in raw}
    return JobRecord(**known)


def _unlink_quietly(name: str) -> None:
    try:
        os.unlink(name)
    except OSError:
        pass
