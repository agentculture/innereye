"""t5: provenance capture and the refusal to clobber prior evidence."""

from __future__ import annotations

import json

import pytest

from innereye import provenance as prov
from innereye.cli._errors import CliError


def _prov(**over):
    base = dict(backend="comfyui", task="text_to_image", seed=7, container="png")
    base.update(over)
    return prov.Provenance(**base)


def test_innereye_chooses_the_seed_when_none_is_given() -> None:
    a, b = prov.choose_seed(), prov.choose_seed()
    assert isinstance(a, int) and a >= 0
    assert a != b  # not a constant, and not a backend default


def test_explicit_seed_is_honoured() -> None:
    assert prov.choose_seed(1234) == 1234


def test_negative_and_bool_seeds_are_refused() -> None:
    with pytest.raises(CliError):
        prov.choose_seed(-1)
    with pytest.raises(CliError):
        prov.choose_seed(True)


def test_seed_must_be_present_in_the_submitted_payload() -> None:
    """A seed only in the sidecar tells you nothing about what was generated."""
    payload = {"25": {"inputs": {"noise_seed": 99}}}
    prov.assert_seed_submitted(payload, 99)
    with pytest.raises(CliError) as exc:
        prov.assert_seed_submitted(payload, 7)
    assert "not present in the compiled graph" in exc.value.message


def test_container_is_recorded_explicitly() -> None:
    assert prov.container_for("a.png") == "png"
    assert prov.container_for("a.webp") == "webp"
    assert prov.container_for("a.weird") == "unknown"


def test_artifact_and_sidecar_are_written_together(tmp_path) -> None:
    art, side = prov.write_artifact(tmp_path / "out.png", b"bytes", _prov())
    assert art.read_bytes() == b"bytes"
    assert json.loads(side.read_text())["seed"] == 7
    assert side.name == "out.png.json"


def test_same_seed_twice_refuses_to_destroy_the_first_result(tmp_path) -> None:
    """The challenge-pass finding: predictable paths + seeds = silent overwrite."""
    target = tmp_path / "out.png"
    prov.write_artifact(target, b"first", _prov())
    with pytest.raises(CliError) as exc:
        prov.write_artifact(target, b"second", _prov())
    assert exc.value.code == 1
    assert "refusing to overwrite" in exc.value.message
    assert target.read_bytes() == b"first"


def test_overwrite_is_possible_but_explicit(tmp_path) -> None:
    target = tmp_path / "out.png"
    prov.write_artifact(target, b"first", _prov())
    prov.write_artifact(target, b"second", _prov(), overwrite=True)
    assert target.read_bytes() == b"second"


def test_an_orphaned_sidecar_also_blocks(tmp_path) -> None:
    """Refusal is checked on BOTH paths before either is written."""
    target = tmp_path / "out.png"
    prov.sidecar_path(target).write_text("{}")
    with pytest.raises(CliError):
        prov.write_artifact(target, b"x", _prov())
    assert not target.exists()


def test_sidecar_round_trips(tmp_path) -> None:
    target = tmp_path / "out.png"
    prov.write_artifact(target, b"x", _prov(sampler="euler", steps=20, width=1024))
    back = prov.read_sidecar(target)
    assert back["sampler"] == "euler" and back["steps"] == 20 and back["width"] == 1024


def test_missing_sidecar_is_a_user_error(tmp_path) -> None:
    with pytest.raises(CliError) as exc:
        prov.read_sidecar(tmp_path / "absent.png")
    assert exc.value.code == 1
