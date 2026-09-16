"""Tests for the introspection verbs: overview, cli overview, doctor."""

from __future__ import annotations

import argparse as _argparse
import json

import pytest

from innereye.cli import _build_parser, main
from innereye.explain.catalog import ENTRIES

# --- overview -------------------------------------------------------------


def test_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["overview"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# innereye" in out
    assert "Identity" in out


def test_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "innereye"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_overview_graceful_on_bad_path(capsys: pytest.CaptureFixture[str]) -> None:
    # Rubric contract: descriptive verbs never hard-fail on a missing target.
    rc = main(["overview", "/no/such/path/here"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


# --- cli overview ---------------------------------------------------------


def test_cli_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["cli", "overview"])
    assert rc == 0
    assert "# innereye cli" in capsys.readouterr().out


def test_cli_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["cli", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "innereye cli"
    assert isinstance(payload["sections"], list)


def test_cli_noun_bare_is_non_empty(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["cli"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_cli_overview_unknown_flag_structured_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `cli overview` parse errors must route through the structured error
    # contract (error:/hint: + exit 1), not argparse's default stderr/exit 2.
    with pytest.raises(SystemExit) as exc:
        main(["cli", "overview", "--bogus"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


# --- doctor ---------------------------------------------------------------


def test_doctor_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["doctor"])
    assert rc in (0, 1)
    assert "innereye doctor" in capsys.readouterr().out


def test_doctor_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["doctor", "--json"])
    assert rc in (0, 1)
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload["healthy"], bool)
    assert isinstance(payload["checks"], list)
    assert payload["checks"]
    for check in payload["checks"]:
        assert {"id", "passed", "severity", "message", "remediation"} <= set(check)


def test_doctor_recognizes_declared_backend(capsys: pytest.CaptureFixture[str]) -> None:
    """The repo's own declared backend must be a known one — doctor stays healthy.

    Guards the backend-consistency invariant: a promotion that changes
    ``culture.yaml``'s backend without teaching ``doctor`` the matching prompt
    file would otherwise slip through (the shape tests above tolerate rc==1).
    """
    rc = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    messages = " ".join(str(c["message"]) for c in payload["checks"])
    assert "unknown backend" not in messages
    assert rc == 0
    assert payload["healthy"] is True


# --- generic surface consistency (added with the render/job verbs) -----------
#
# The challenge pass found that NOTHING mechanically checked that a registered
# command has a catalog entry or a --json flag: the only generic gate walked
# catalog.ENTRIES outward, never the argparse tree inward. These tests close
# that gap, so a future verb cannot ship half-registered.


def _walk(parser, path=()):
    """Yield (path, parser) for every registered command and sub-command."""
    for action in parser._actions:
        if isinstance(action, _argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                here = path + (name,)
                yield here, subparser
                yield from _walk(subparser, here)


def _registered_paths():
    return [path for path, _ in _walk(_build_parser())]


def test_every_registered_command_has_a_catalog_entry() -> None:
    missing = [p for p in _registered_paths() if p not in ENTRIES]
    assert not missing, f"registered but not in explain catalog: {missing}"


def test_every_registered_command_accepts_json() -> None:
    """argparse does not inherit --json; every level must declare its own."""
    offenders = []
    for path, parser in _walk(_build_parser()):
        flags = {opt for action in parser._actions for opt in action.option_strings}
        if "--json" not in flags:
            offenders.append(path)
    assert not offenders, f"commands missing --json: {offenders}"


def test_every_noun_with_action_verbs_exposes_overview() -> None:
    """The rubric's overview_cli_noun_exists check, asserted in pytest too."""
    parser = _build_parser()
    for path, subparser in _walk(parser):
        children = {
            name
            for action in subparser._actions
            if isinstance(action, _argparse._SubParsersAction)
            for name in action.choices
        }
        if children:
            assert "overview" in children, f"noun {path} has verbs {children} but no overview"


def test_render_and_job_are_registered() -> None:
    paths = _registered_paths()
    assert ("render",) in paths
    for verb in ("overview", "status", "fetch", "cancel"):
        assert ("job", verb) in paths
