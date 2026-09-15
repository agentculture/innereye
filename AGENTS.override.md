# AGENTS.override.md

This file is the **context layer** for the Pi harness (the `pi` CLI, and the
`associate` non-coding harness modelled on it) when it runs inside this repo.
Pi's CONTEXT loader concatenates `AGENTS.md` or `CLAUDE.md` from its user-level
config directory (see Pi's own docs), each parent directory, and the working
directory — but an `AGENTS.override.md`
present in a directory replaces that directory's `AGENTS.md`/`CLAUDE.md` entry
outright rather than adding to it. That is why this repo ships this file
instead of an `AGENTS.md`: Pi must **not** inherit `CLAUDE.md` (the Claude Code
guidance file) — the two harnesses read the same repository very differently,
and `CLAUDE.md` assumes a coding session with full repo-write authority that
Pi's non-coding lane does not have.

The identity and behavioral bounds for that lane — who Pi is here, what it may
and may not do — live one layer up, in Pi's **system prompt** file,
[`.pi/SYSTEM.md`](.pi/SYSTEM.md). That file replaces Pi's default
coding-assistant system prompt entirely. This file is project *context* only:
what the repo is and how it is laid out, not who is reading it.

## What this project is

`innereye` is the AgentCulture mesh's **visual output surface**: an agent-first
CLI that renders and previews images and videos from **text, image, or
embedding** inputs. It starts with a ComfyUI backend but is deliberately not
locked to one — generation backends are pluggable behind a portable
`(task, inputs, params)` "recipe" each adapter compiles into its native form.

**Read this before answering a question about what innereye does:** the domain
is *not implemented yet*. On disk today there is only the
`culture-agent-template` scaffold — six agent-first verbs (`whoami`, `learn`,
`explain`, `overview`, `doctor`, `cli overview`), four harness prompt files, the
vendored skill kit, and CI. There is no `render` verb, no backend adapter, and
no job store. The intended design lives in
[issue #1](https://github.com/agentculture/innereye/issues/1) and
[`CLAUDE.md`](CLAUDE.md); when you summarize it, say plainly that it is design,
not shipped behaviour.

It is a sibling to [`guildmaster`](https://github.com/agentculture/guildmaster)
(the skills supplier), [`steward`](https://github.com/agentculture/steward)
(alignment), and [`teken`](https://github.com/agentculture/teken) (the CLI
scaffolder this package is cited from), and expects to exchange vectors with
[`embeddings-cli`](https://github.com/agentculture/embeddings-cli) and previews
with [`storybook-cli`](https://github.com/agentculture/storybook-cli).

## Four harnesses, four files, no shared base

This repo's root carries one prompt file per harness, each read by exactly
one of them — there is deliberately no shared `AGENTS.md` base for them to
cascade from:

- **Claude Code** reads [`CLAUDE.md`](CLAUDE.md).
- **Pi / associate** reads this file (`AGENTS.override.md`) for context, plus
  [`.pi/SYSTEM.md`](.pi/SYSTEM.md) for its system prompt.
- **colleague** reads [`AGENTS.colleague.md`](AGENTS.colleague.md) (the start
  of colleague's own cascade — see that file).
- **Qwen Code** reads [`QWEN.md`](QWEN.md).

If you are reading this as a human, `CLAUDE.md` is the fullest write-up of the
repo's conventions and is the one to read first; the other three exist to keep
each non-Claude harness from silently inheriting Claude-specific instructions
it cannot act on the same way.

## Identity

Declared in `culture.yaml`:

```yaml
agents:
- suffix: innereye
  backend: claude
```

innereye's *mesh* resident runs on `backend: claude`, so `CLAUDE.md` is
the live resident prompt. A Pi session working in a clone of this repo is a
**local tool session**, not the mesh resident — it reads this file and
`.pi/SYSTEM.md` regardless of what `culture.yaml` declares, and running `pi`
here neither requires nor changes that declaration.

(A repo that wants `associate` as its *mesh* resident declares
`backend: colleague` with `model: associate` — see `docs/skill-sources.md`.
That is a per-repo choice; innereye does not use it.)

## Layout (what you can read/find/summarize here)

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

## Conventions worth knowing before you answer a question about this repo

- The vendored skills under `.claude/skills/` are cited **verbatim** from
  guildmaster — never propose editing their scripts; the fix belongs upstream
  (`docs/skill-sources.md` has the re-sync procedure).
- The claim of *what innereye is* is repeated across four harness prompt
  files, `README.md`, `pyproject.toml`, and three code strings
  (`cli/__init__.py`, `_commands/learn.py`, `explain/catalog.py`). If you are
  asked whether the docs agree, sweep them together:
  `git grep -niF 'visual output surface'`.
- Every PR bumps the version (`version-bump` skill); CI's `version-check` job
  blocks merge otherwise.
- This file describes the repo **as it exists on disk today**. If you are
  asked to update it, keep claims grounded in checked-in reality.
