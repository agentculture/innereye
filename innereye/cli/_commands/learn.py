"""``innereye learn`` — the learnability affordance.

Prints a structured self-teaching prompt. Must satisfy the agent-first rubric:
>=200 chars and mention purpose, command map, exit codes, --json, and explain.
"""

from __future__ import annotations

import argparse

from innereye import __version__
from innereye.cli._output import emit_result

_TEXT = """\
innereye — the mesh's visual output surface.

Purpose
-------
Render and preview images and videos from text, image, or embedding inputs.
Generation backends are pluggable behind one agent-first CLI: a portable
(task, inputs, params) recipe is compiled by each adapter into its native form,
starting with ComfyUI. An adapter declares the tasks and input modalities it
supports; an unsupported request fails honestly naming a backend that can,
never silently downgrading. Generation is modelled as jobs, and provenance
(backend, model, seed, params, recipe) travels with every artifact.

STATUS: scaffold. No generation verb is implemented yet — the commands below
are the agent-first baseline only. See:
https://github.com/agentculture/innereye/issues/1

Commands
--------
  innereye whoami             Identity from culture.yaml.
  innereye learn              This self-teaching prompt.
  innereye explain <path>...  Markdown docs for any noun/verb path.
  innereye overview           Descriptive snapshot of the agent.
  innereye doctor             Check the agent-identity invariants.
  innereye cli overview       Describe the CLI surface itself.

Machine-readable output
-----------------------
Every command supports --json. Errors in JSON mode emit
{"code", "message", "remediation"} to stderr. Stdout and stderr never mix.

Exit-code policy
----------------
  0 success
  1 user-input error (bad flag, bad path, missing arg)
  2 environment / setup error
  3+ reserved

More detail
-----------
  innereye explain innereye
"""


def _as_json_payload() -> dict[str, object]:
    return {
        "tool": "innereye",
        "version": __version__,
        "purpose": (
            "Render and preview images and videos from text, image, or embedding "
            "inputs, via pluggable generation backends (ComfyUI first)."
        ),
        "status": "scaffold: no generation verb implemented yet",
        "commands": [
            {"path": ["whoami"], "summary": "Identity probe from culture.yaml."},
            {"path": ["learn"], "summary": "Self-teaching prompt."},
            {"path": ["explain"], "summary": "Markdown docs by path."},
            {"path": ["overview"], "summary": "Descriptive snapshot of the agent."},
            {"path": ["doctor"], "summary": "Check the agent-identity invariants."},
            {"path": ["cli", "overview"], "summary": "Describe the CLI surface."},
        ],
        "exit_codes": {
            "0": "success",
            "1": "user-input error",
            "2": "environment/setup error",
        },
        "json_support": True,
        "explain_pointer": "innereye explain <path>",
    }


def cmd_learn(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        emit_result(_as_json_payload(), json_mode=True)
    else:
        emit_result(_TEXT, json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "learn",
        help="Print a structured self-teaching prompt for agent consumers.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_learn)
