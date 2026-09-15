# QWEN.md

This file provides guidance to Qwen Code when working with code in this
repository. Qwen Code's context loader reads exactly `QWEN.md` and `AGENTS.md`
in a directory; this repo deliberately ships only `QWEN.md` — there is no
`AGENTS.md` here (each harness gets its own file; see "Prompt files by
harness" below), so this file is the sole source of project guidance for a
Qwen Code session.

## What this project is

`innereye` is the AgentCulture mesh's **visual output surface**: an agent-first
CLI that renders and previews images and videos from **text, image, or
embedding** inputs. It starts with a ComfyUI backend but is not locked to one —
generation backends are pluggable behind a portable `(task, inputs, params)`
**recipe** that each adapter compiles into its native form (a filled ComfyUI
template graph; a single HTTP request for a hosted API).

**Status: scaffold.** The domain is not implemented yet. On disk today there is
only the `culture-agent-template` baseline — the six agent-first verbs, four
harness prompt files, the vendored skill kit, and CI. There is no `render`
verb, no backend adapter, and no job store. The intended design lives in
[issue #1](https://github.com/agentculture/innereye/issues/1) and
[`CLAUDE.md`](CLAUDE.md).

It is a sibling to [`guildmaster`](https://github.com/agentculture/guildmaster)
(the **skills supplier**), [`steward`](https://github.com/agentculture/steward)
(**alignment** — `steward doctor`, the sibling-pattern baseline), and
[`teken`](https://github.com/agentculture/teken) (the **afi-cli** "Agent First
Interface" scaffolder this CLI is cited from) within the Organic Development
framework. Vectors come from
[`embeddings-cli`](https://github.com/agentculture/embeddings-cli); shareable
previews hand off to
[`storybook-cli`](https://github.com/agentculture/storybook-cli).

## Domain rules that shape every verb

- **The three inputs** — text, images (init/mask/control/reference), and
  **embeddings**. Embeddings are first-class: an agent holding a CLIP vector, a
  latent or an IP-Adapter embedding conditions generation on it directly,
  without round-tripping through English.
- **Capability negotiation is mandatory.** Each adapter declares the tasks and
  modalities it supports; an unsupported request **fails honestly**, naming a
  backend that could do it. Never silently downgrade — approximating an
  embedding as text and generating anyway is indistinguishable in the output.
- **Generation is modelled as jobs** (submit / status / fetch, blocking wait as
  a convenience), and job state survives process exit.
- **Provenance is output**: backend, model, seed, resolution, sampler/steps, the
  full recipe, the exact graph where applicable — beside the artifact. Seeds are
  captured explicitly, never left to a backend default.
- **Write verbs are dry-run by default; `--apply` commits.** A dry run prints
  the compiled recipe and the resolved backend.
- **Non-goals:** not image *understanding* (that is `embeddings-lens` and
  peers), not a model zoo/trainer, not a ComfyUI reimplementation, not a hosting
  service.

## Prompt files by harness

This repo's root carries one prompt file per agent harness, each read by
exactly one of them — there is no shared base file for them to inherit from:

- **Claude Code** → [`CLAUDE.md`](CLAUDE.md) (the fullest write-up; read it
  first if you are new to the repo).
- **Pi / associate** → [`AGENTS.override.md`](AGENTS.override.md) for context,
  plus [`.pi/SYSTEM.md`](.pi/SYSTEM.md) for its system prompt.
- **colleague** → [`AGENTS.colleague.md`](AGENTS.colleague.md).
- **Qwen Code** → this file.

## Identity

Declared in `culture.yaml`:

```yaml
agents:
- suffix: innereye
  backend: claude
```

`backend: claude` fixes the *mesh resident* prompt file to `CLAUDE.md` — the
mesh runtime reads that file, not this one. A Qwen Code session working in a
clone of this repo is a separate, local tool session; it reads `QWEN.md`
regardless of what `culture.yaml` declares, and running Qwen Code here neither
requires nor changes that declaration. The declaration and the resident prompt
together satisfy the two invariants `steward doctor` verifies:
**prompt-file-present** and **backend-consistency** (`claude` ↔ `CLAUDE.md`).

## Keeping the docs honest

The claim of *what innereye is* is repeated in four harness prompt files,
`README.md`, `pyproject.toml`'s `description`, and three code strings
(`innereye/cli/__init__.py`'s parser description, `_commands/learn.py`'s `_TEXT`
and `_as_json_payload()`, and `explain/catalog.py`'s `_ROOT`). Nothing in CI
checks that they still agree — when the description changes, sweep them
together:

```bash
git grep -niF 'visual output surface'
```

Identity itself needs no code change: `whoami` and `doctor` read `suffix` and
`backend` from `culture.yaml` at runtime.

## The CLI

The CLI is cited (cite-don't-import) from teken's `python-cli` reference
(`teken cli cite`), so the runtime package has **no third-party dependencies**;
`teken` (a.k.a. `afi-cli`) is a dev dependency only. Agent-first verbs:

- `innereye whoami` — identity from `culture.yaml`.
- `innereye learn` — structured self-teaching prompt.
- `innereye explain <path>` — markdown docs for any noun/verb.
- `innereye overview` — descriptive snapshot of the agent.
- `innereye doctor` — check the agent-identity invariants.
- `innereye cli overview` — describe the CLI surface itself.

Conventions: every command supports `--json`; results go to stdout, errors and
diagnostics to stderr (never mixed); exit codes are `0` success, `1` user
error, `2` environment error, `3+` reserved. The agent-first rubric is
enforced in CI by `teken cli doctor . --strict`.

## Skills

`.claude/skills/` vendors the **canonical guildmaster skill kit**
(cite-don't-import). Provenance and the re-sync procedure live in
`docs/skill-sources.md`. Do not reformat or edit vendored scripts — re-sync
from guildmaster instead.

## Conventions

- **Every PR bumps the version** — even docs/config/CI. Use the
  `version-bump` skill; the `version-check` CI job blocks merge otherwise.
- **Tests**: `uv run pytest -n auto`. **Lint**: black, isort, flake8 (line
  length 100), bandit, markdownlint.
- **Deploy**: pushing to `main` publishes to PyPI via Trusted Publishing
  (`.github/workflows/publish.yml`); PRs do a TestPyPI dry-run.

## Layout

```text
innereye/   agent-first CLI (cited from teken's python-cli reference)
  cli/                    parser, error/output contract, _commands/ (verbs)
  explain/                markdown catalog for `explain`
tests/                    pytest smoke + introspection tests
.claude/skills/           vendored guildmaster skill kit (cite-don't-import)
docs/skill-sources.md     skill provenance ledger
culture.yaml              mesh identity (suffix + backend)
.github/workflows/        tests + deploy (PyPI Trusted Publishing)
```

This file describes the repository **as it exists on disk today**. When you
edit, keep claims grounded in checked-in reality; if a section drifts ahead of
reality, mark it `(planned)` or move it under a `## Roadmap` heading. For the
full set of workflow conventions (worktree layout, memory discipline,
`ask-colleague` usage), see [`CLAUDE.md`](CLAUDE.md) — those conventions apply
to work in this repo regardless of which harness is doing it.
