"""t4: the job store -- survives process exit, versioned, concurrency-safe."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from innereye import jobs
from innereye.cli._errors import CliError


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("INNEREYE_JOB_STORE", str(tmp_path / "jobs"))
    return tmp_path / "jobs"


def _record(**over):
    base = dict(backend="comfyui", backend_job_id="abc-123", task="text_to_image", output_node="9")
    base.update(over)
    return jobs.record_for(**base)


def test_schema_version_is_written_from_the_first_release() -> None:
    path = jobs.save(_record())
    raw = json.loads(path.read_text())
    assert raw["schema_version"] == jobs.SCHEMA_VERSION


def test_round_trip() -> None:
    rec = _record()
    jobs.save(rec)
    loaded = jobs.load(rec.id)
    assert loaded.backend_job_id == "abc-123"
    assert loaded.state == jobs.STATE_PENDING


def test_two_concurrent_submits_produce_distinct_collectable_records() -> None:
    a, b = _record(), _record()
    assert a.id != b.id
    jobs.save(a)
    jobs.save(b)
    assert {jobs.load(a.id).id, jobs.load(b.id).id} == {a.id, b.id}
    assert len(list(jobs.iter_jobs())) == 2


def test_a_separate_process_can_collect_what_this_one_submitted(_store) -> None:
    """The honesty condition: submit in one invocation, collect in another."""
    rec = _record()
    jobs.save(rec)
    code = (
        "import os,sys;"
        f"os.environ['INNEREYE_JOB_STORE']={str(_store)!r};"
        "from innereye import jobs;"
        f"print(jobs.load({rec.id!r}).backend_job_id)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "abc-123"


def test_unknown_job_is_a_user_error_not_a_crash() -> None:
    with pytest.raises(CliError) as exc:
        jobs.load("nosuchjob")
    assert exc.value.code == 1


def test_a_newer_schema_fails_closed(_store) -> None:
    rec = _record()
    path = jobs.save(rec)
    raw = json.loads(path.read_text())
    raw["schema_version"] = jobs.SCHEMA_VERSION + 1
    path.write_text(json.dumps(raw))
    with pytest.raises(CliError) as exc:
        jobs.load(rec.id)
    assert exc.value.code == 2
    assert "understands v" in exc.value.message


def test_lost_backend_job_has_its_own_state() -> None:
    """A restarted server invalidates prompt_ids; that is reportable, not a hang."""
    rec = _record()
    rec.state = jobs.STATE_UNKNOWN
    jobs.save(rec)
    assert jobs.load(rec.id).state == jobs.STATE_UNKNOWN
    assert not jobs.load(rec.id).is_terminal()


def test_invalid_state_is_refused() -> None:
    rec = _record()
    rec.state = "vibing"
    with pytest.raises(CliError):
        jobs.save(rec)


def test_corrupt_record_is_skipped_by_iteration(_store) -> None:
    jobs.save(_record())
    (_store / "garbage.json").write_text("{not json")
    assert len(list(jobs.iter_jobs())) == 1
