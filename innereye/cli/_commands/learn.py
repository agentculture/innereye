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

Commands
--------
  innereye render             Render an image or video (dry-run by default).
  innereye job overview       List submitted jobs and the job store.
  innereye job status <id>    Report one job's state.
  innereye job fetch <id>     Download a finished job's artifacts.
  innereye job cancel <id>    Stop a queued or running job.
  innereye whoami             Identity from culture.yaml.
  innereye learn              This self-teaching prompt.
  innereye explain <path>...  Markdown docs for any noun/verb path.
  innereye overview           Descriptive snapshot of the agent.
  innereye doctor             Check the agent-identity invariants.
  innereye cli overview       Describe the CLI surface itself.

Rendering
---------
Every write verb is dry-run by default; --apply commits. You supply the
template graph and its field-to-node mapping -- innereye ships no default
graph, because node ids differ per graph. Fetch a demo pair with
'innereye render --demo flux-text-to-image'. Video artifacts land as .webp.

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
        "status": "render and job verbs implemented; ComfyUI is the only backend",
        "commands": [
            {"path": ["render"], "summary": "Render an image or video (dry-run by default)."},
            {"path": ["job", "overview"], "summary": "List submitted jobs."},
            {"path": ["job", "status"], "summary": "Report one job's state."},
            {"path": ["job", "fetch"], "summary": "Download a finished job's artifacts."},
            {"path": ["job", "cancel"], "summary": "Stop a queued or running job."},
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
