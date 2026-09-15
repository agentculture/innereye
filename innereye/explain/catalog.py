"""Markdown catalog for ``innereye explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("innereye",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# innereye

The AgentCulture mesh's **visual output surface**: render and preview images and
videos from **text, image, or embedding** inputs. Generation backends are
pluggable behind one agent-first CLI — a portable `(task, inputs, params)`
recipe that each adapter compiles into its native form, starting with ComfyUI.

Design commitments:

- Embeddings are a first-class input, not an afterthought.
- Adapters declare their capabilities; an unsupported request fails honestly
  naming a backend that could serve it, and **never silently downgrades**.
- Generation is modelled as jobs (submit / status / fetch); job state survives
  process exit.
- Provenance (backend, model, seed, resolution, sampler/steps, recipe) travels
  with every artifact.
- Write verbs are dry-run by default; `--apply` commits.

**Status: scaffold.** No generation verb is implemented yet; the verbs below are
the agent-first baseline. The design brief is
<https://github.com/agentculture/innereye/issues/1>.

## Verbs

- `innereye whoami` — identity probe from `culture.yaml`.
- `innereye learn` — structured self-teaching prompt.
- `innereye explain <path>` — markdown docs for any noun/verb.
- `innereye overview` — descriptive snapshot of the agent.
- `innereye doctor` — check the agent-identity invariants.
- `innereye cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `innereye explain whoami`
- `innereye explain doctor`
"""

_WHOAMI = """\
# innereye whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    innereye whoami
    innereye whoami --json
"""

_LEARN = """\
# innereye learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    innereye learn
    innereye learn --json
"""

_EXPLAIN = """\
# innereye explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    innereye explain innereye
    innereye explain whoami
    innereye explain --json <path>
"""

_OVERVIEW = """\
# innereye overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    innereye overview
    innereye overview --json
"""

_DOCTOR = """\
# innereye doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`claude` → `CLAUDE.md`), plus a
skills-present check. Exits 1 when unhealthy.

prompt-file-present requires the *resident* prompt the declared backend
actually reads. Other harness prompt files recognized under the same backend
name (`AGENTS.override.md`, `.pi/SYSTEM.md`, `QWEN.md`) belong to
interactively available harnesses the mesh daemon never loads; they are
reported by the informational harness-prompts check and never substituted.

## Usage

    innereye doctor
    innereye doctor --json
"""

_CLI = """\
# innereye cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    innereye cli overview
    innereye cli overview --json
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("innereye",): _ROOT,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
}
