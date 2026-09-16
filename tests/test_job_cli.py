"""t9: the job noun group -- overview, status, fetch, cancel."""

from __future__ import annotations

import json

import pytest

from innereye import jobs
from innereye.backends import _http
from innereye.cli import main
from innereye.cli._errors import CliError

COMPLETED = {
    "id": "pid",
    "status": "completed",
    "outputs": {"9": {"images": [{"filename": "o_00001_.png", "subfolder": "", "type": "output"}]}},
    "execution_status": {"status_str": "success", "messages": []},
}


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("INNEREYE_JOB_STORE", str(tmp_path / "jobs"))


@pytest.fixture
def submitted():
    rec = jobs.record_for(
        backend="comfyui",
        backend_job_id="pid",
        task="text_to_image",
        output_node="9",
        recipe={"params": {"seed": 11, "width": 64}},
    )
    jobs.save(rec)
    return rec


def _routes(monkeypatch, routes, blob=b"\x89PNG"):
    def match(url):
        for frag in sorted(routes, key=len, reverse=True):
            if frag in url:
                return routes[frag]
        return 404, {}

    monkeypatch.setattr(_http, "get_json", lambda url, **k: match(url))
    monkeypatch.setattr(_http, "post_json", lambda url, p=None, **k: match(url))
    monkeypatch.setattr(_http, "get_bytes", lambda url, **k: (200, blob))


def test_overview_describes_the_noun_and_the_store(capsys) -> None:
    rc = main(["job", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["noun"] == "job"
    assert payload["schema_version"] == jobs.SCHEMA_VERSION
    assert "cancelled" in payload["states"]
    assert "unknown" in payload["states"]
    assert set(payload["verbs"]) == {"overview", "status", "fetch", "cancel"}


def test_bare_job_prints_the_overview(capsys) -> None:
    assert main(["job"]) == 0
    assert "innereye job" in capsys.readouterr().out


def test_overview_lists_known_jobs(submitted, capsys) -> None:
    main(["job", "overview", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["jobs"][0]["id"] == submitted.id


def test_status_refreshes_from_the_backend(submitted, monkeypatch, capsys) -> None:
    _routes(monkeypatch, {"/api/jobs": (200, {}), "/api/jobs/pid": (200, COMPLETED)})
    rc = main(["job", "status", submitted.id, "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["state"] == "completed"
    assert jobs.load(submitted.id).state == "completed"  # persisted


def test_fetch_writes_artifact_and_provenance(submitted, monkeypatch, tmp_path, capsys) -> None:
    _routes(monkeypatch, {"/api/jobs": (200, {}), "/api/jobs/pid": (200, COMPLETED)})
    out = tmp_path / "renders"
    rc = main(["job", "fetch", submitted.id, "--out", str(out), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    artifact = payload["artifacts"][0]
    assert artifact["artifact"].endswith("o_00001_.png")
    side = json.loads(open(artifact["provenance"]).read())
    assert side["seed"] == 11
    assert side["container"] == "png"
    assert side["backend"] == "comfyui"
    assert side["backend_job_id"] == "pid"


def test_fetch_twice_refuses_to_destroy_the_first(submitted, monkeypatch, tmp_path, capsys) -> None:
    _routes(monkeypatch, {"/api/jobs": (200, {}), "/api/jobs/pid": (200, COMPLETED)})
    out = tmp_path / "renders"
    main(["job", "fetch", submitted.id, "--out", str(out)])
    capsys.readouterr()
    rc = main(["job", "fetch", submitted.id, "--out", str(out)])
    assert rc == 1
    assert "refusing to overwrite" in capsys.readouterr().err


def test_preview_is_reported_on_stderr_not_mixed_into_stdout(
    submitted, monkeypatch, tmp_path, capsys
) -> None:
    _routes(
        monkeypatch, {"/api/jobs": (200, {}), "/api/jobs/pid": (200, COMPLETED)}, blob=b"not-a-png"
    )
    main(["job", "fetch", submitted.id, "--out", str(tmp_path), "--preview", "--json"])
    captured = capsys.readouterr()
    json.loads(captured.out)  # stdout is exactly one JSON payload
    assert "preview:" in captured.err


def test_cancel_marks_the_record(submitted, monkeypatch, capsys) -> None:
    _routes(monkeypatch, {"/api/jobs": (200, {}), "/cancel": (200, {})})
    rc = main(["job", "cancel", submitted.id, "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["state"] == "cancelled"
    assert jobs.load(submitted.id).state == "cancelled"


def test_unknown_job_is_a_clean_user_error(capsys) -> None:
    rc = main(["job", "status", "nosuch"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_every_job_subverb_accepts_json(capsys) -> None:
    for verb in ("overview",):
        assert main(["job", verb, "--json"]) == 0
        json.loads(capsys.readouterr().out)


# --- fixes from the PR #3 review (Qodo) ---


def test_lost_job_ends_the_wait_instead_of_burning_the_timeout(submitted, monkeypatch) -> None:
    """The backend said it no longer knows this job; polling cannot change that."""
    _routes(monkeypatch, {"/api/jobs": (200, {}), "/api/jobs/pid": (404, {})})
    from innereye.backends.comfyui import ComfyUIBackend
    from innereye.cli._commands.job import wait_for

    backend = ComfyUIBackend()
    with pytest.raises(CliError) as exc:
        wait_for(backend, submitted, timeout=900.0)
    assert exc.value.code == 2
    assert "no longer knows" in exc.value.message


def test_follow_up_targets_the_endpoint_the_job_was_submitted_to(monkeypatch) -> None:
    """A remote render must not be followed up against loopback."""
    import argparse

    from innereye.cli._commands.job import _backend

    rec = jobs.record_for(
        backend="comfyui",
        backend_job_id="p",
        task="text_to_image",
        output_node="9",
        endpoint="http://10.0.0.5:8188",
    )
    args = argparse.Namespace(endpoint="http://127.0.0.1:8188", timeout=5.0)
    assert _backend(args, rec).endpoint == "http://10.0.0.5:8188"
    # an explicit override still wins
    args.endpoint = "http://10.0.0.9:8188"
    assert _backend(args, rec).endpoint == "http://10.0.0.9:8188"


def test_traversal_filename_from_the_backend_is_refused(
    submitted, monkeypatch, tmp_path, capsys
) -> None:
    """A compromised backend must not choose where bytes land."""
    evil = {
        "id": "pid",
        "status": "completed",
        "outputs": {
            "9": {"images": [{"filename": "../../escaped.png", "subfolder": "", "type": "output"}]}
        },
        "execution_status": {"status_str": "success", "messages": []},
    }
    _routes(monkeypatch, {"/api/jobs": (200, {}), "/api/jobs/pid": (200, evil)})
    rc = main(["job", "fetch", submitted.id, "--out", str(tmp_path / "renders")])
    assert rc == 2
    assert "refusing backend filename" in capsys.readouterr().err
    assert not (tmp_path / "escaped.png").exists()


def test_sidecar_records_effective_settings_not_just_flags(monkeypatch, tmp_path, capsys) -> None:
    """A render that relied on graph defaults must still record what it used."""
    rec = jobs.record_for(
        backend="comfyui",
        backend_job_id="pid",
        task="text_to_image",
        output_node="9",
        recipe={"params": {"seed": 5}},
        resolved={
            "models": ["flux1-dev.safetensors"],
            "sampling": {"steps": 20},
            "size": {"width": 1024, "height": 1024},
            "graph_digest": "deadbeef",
        },
        input_digests={"image": "abc123"},
        endpoint="http://127.0.0.1:8188",
    )
    jobs.save(rec)
    _routes(monkeypatch, {"/api/jobs": (200, {}), "/api/jobs/pid": (200, COMPLETED)})
    main(["job", "fetch", rec.id, "--out", str(tmp_path), "--json"])
    side = json.loads(
        open(json.loads(capsys.readouterr().out)["artifacts"][0]["provenance"]).read()
    )
    assert side["models"] == ["flux1-dev.safetensors"]
    assert side["size"]["width"] == 1024
    assert side["graph_digest"] == "deadbeef"
    assert side["input_digests"]["image"] == "abc123"
    assert side["endpoint"] == "http://127.0.0.1:8188"
