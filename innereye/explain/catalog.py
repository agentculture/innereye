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

**Status:** `render` and the `job` noun group are implemented against a ComfyUI
backend. Still `(planned)`: a second adapter, and embedding inputs — no shipped
template graph exposes an embedding node, so `embedding_to_image` is declared
*unsupported* and refused rather than approximated. The design brief is
<https://github.com/agentculture/innereye/issues/1>.

## Verbs

- `innereye render` — render an image or video (dry-run by default).
- `innereye job overview|status|fetch|cancel` — follow up submitted jobs.
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

_RENDER = """\
# innereye render

Compile a portable recipe into an operator-supplied ComfyUI template graph and
submit it as a job. **Dry-run by default** — a bare `render` prints the compiled
recipe and the resolved backend and submits nothing; `--apply` commits.

## The graph is a pair

innereye ships no default template graph. Node ids are not stable across graphs
(flux saves at node `9`, hidream at `12`), so a graph is only usable together
with a mapping from recipe fields to node input paths:

    {"output_node": "9", "fields": {"inputs.prompt": "6.inputs.text"}}

By default the mapping is read from `<graph>.mapping.json`; `--mapping`
overrides. Export a graph from ComfyUI with **Save (API Format)**.

## Usage

    innereye render --prompt "a snow leopard" --graph flux.api.json
    innereye render --prompt "a snow leopard" --graph flux.api.json --apply --wait --preview
    innereye render --demo flux-text-to-image --into graphs/
    innereye render --prompt "..." --graph wan.api.json --task text_to_video --apply

`--demo` is a separately named mode that downloads one of NVIDIA's playbook
graphs plus a matching mapping. It is the only path here that touches the
network, and it downloads the **graph**, not the model weights.

## Notes

- Video artifacts land as `.webp` (the playbook graphs end in `SaveAnimatedWEBP`);
  the container is recorded in the provenance sidecar.
- A capability mismatch is a user error naming an alternative, never a
  best-effort render.
- ComfyUI keeps its own copy of every artifact under its output directory,
  named by an auto-incrementing counter. innereye does not clean that up.
"""

_JOB = """\
# innereye job

Follow up work that outlives the process that started it. `render --apply`
returns a job handle; these verbs collect it — from any later invocation, since
job state is persisted.

## Verbs

    innereye job overview           # the store, the states, and known jobs
    innereye job status <id>        # one job's state
    innereye job fetch <id>         # download artifacts + write provenance
    innereye job cancel <id>        # stop a queued or running job

## States

`pending`, `in_progress`, `completed`, `failed`, `cancelled` come from the
backend. `unknown` is innereye's own: a job this store remembers that the
backend no longer recognises — restarting ComfyUI invalidates its queue ids.

## Notes

- `--wait` is the convenience blocking mode; progress goes to stderr so stdout
  carries exactly one payload.
- Artifacts refuse to overwrite an existing file unless `--overwrite` is passed,
  because overwriting would destroy the earlier result's provenance.
- The store lives at `$INNEREYE_JOB_STORE`, else `$XDG_STATE_HOME/innereye/jobs`.
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
    ("render",): _RENDER,
    ("job",): _JOB,
    ("job", "overview"): _JOB,
    ("job", "status"): _JOB,
    ("job", "fetch"): _JOB,
    ("job", "cancel"): _JOB,
}
