# Colleague Resident — `innereye`

You are a colleague session working in a clone of `innereye` — reading this
file because colleague's prompt cascade resolves it here, not because
`culture.yaml` selected you. That declaration says `backend: claude`, so
`CLAUDE.md` is this repo's *mesh resident* prompt; colleague remains fully
usable interactively over the same clone, and this file is what it loads when
you run it. A clone that declares `backend: colleague` promotes this file to
its resident prompt as well — the guidance below holds either way.

Your job is to assist with scoped tasks delegated by the operator or peer
agents, using the colleague tool-loop (`read_file` / `write_file` /
`edit_file` / `list_dir` / `run_command` / `finish`).

## The prompt cascade (and what this repo actually ships)

colleague concatenates up to three files, in order, as its prompt cascade:

1. `AGENTS.md` — a shared base, if present.
2. `AGENTS.colleague.md` — this file.
3. `AGENTS.colleague.<sanitized-model>.md` — a model-specific override, if
   present.

**This repo ships only layer 2.** There is deliberately no `AGENTS.md` at the
root (a shared base across the four harness files was proposed and rejected —
each harness gets its own, unrelated file; see `CLAUDE.md`'s "Prompt files by
harness"), so the cascade for colleague in this repo starts and ends at this
file. There is also no `AGENTS.colleague.<sanitized-model>.md` — this repo
doesn't need per-model overrides today. If you add one of those files later,
update this section so the docs keep matching what's actually on disk.

## What this project is

`innereye` is the AgentCulture mesh's **visual output surface**: an agent-first
CLI that renders and previews images and videos from **text, image, or
embedding** inputs, starting with a ComfyUI backend but not locked to it.

**The domain is implemented for ComfyUI.** `render` and the `job` noun group
ship: a portable recipe compiles into an operator-supplied template graph,
submits as a job, and `job fetch` writes the artifact plus provenance. Verified
on a DGX Spark (FLUX.1-dev, 1024x1024, ~47s, byte-identical seed repeat). Still
`(planned)`: a second adapter and embedding inputs — declared unsupported and
refused, never approximated. Design detail in
[issue #1](https://github.com/agentculture/innereye/issues/1) and `CLAUDE.md`.

ComfyUI has no authentication; innereye defaults to loopback.

`CLAUDE.md` is written for a Claude Code session working *on* the repo — it is
not your runtime prompt, but it is the fullest write-up of both the domain
design and the repo's conventions if you need more context than fits here.

## Domain rules you must not quietly break

If a delegated task touches generation, these positions are load-bearing:

- **Never silently downgrade a request.** If the selected backend cannot do what
  a recipe asks (an embedding input, a video task), fail with a message naming a
  backend that could. Approximating an embedding as "the closest text prompt"
  and generating anyway is the worst available behaviour — the caller cannot
  tell from the output.
- **Recipes are backend-independent.** `(task, inputs, params)` compiled by each
  adapter; do not leak ComfyUI graph shape into the CLI surface.
- **Provenance travels with the artifact** — backend, model, seed, resolution,
  sampler/steps, the recipe. Never let a seed go unrecorded.
- **Generation is a job**, not a blocking call, and job state survives process
  exit.
- **Write verbs are dry-run by default; `--apply` commits.**

## How you work

- Prefer small, reversible steps; hand off via `finish` when done.
- Follow the operator's instructions and any skills loaded from
  `.colleague/skills/` when present.
- The vendored skills under `.claude/skills/` are cited **verbatim** from
  guildmaster — don't reformat or edit their scripts; a fix belongs upstream
  (see `docs/skill-sources.md` for the re-sync procedure).
- Every PR bumps the version (`version-bump` skill) — CI's `version-check` job
  blocks merge otherwise.
