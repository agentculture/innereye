# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`innereye` is the AgentCulture mesh's **visual output surface**. Agents can
reason about images but cannot produce them; `innereye` closes that gap with an
agent-first CLI that turns a request for a picture or a video into an actual
artifact on disk, with enough provenance that the result can be reproduced or
explained.

One sentence: **render and preview images and videos from text, image, or
embedding inputs — starting with ComfyUI, but not locked to it.**

The full build brief is [issue #1](https://github.com/agentculture/innereye/issues/1)
(`gh issue view 1`). It is a starting position, not a spec — the design notes
below record where this repo currently stands on it.

### Status: scaffold only

**Nothing in the generation domain is implemented yet.** What is on disk today
is the `culture-agent-template` scaffold: the six agent-first verbs (`whoami`,
`learn`, `explain`, `overview`, `doctor`, `cli overview`), the four harness
prompt files, the vendored skill kit, and CI. There is no `render` verb, no
backend adapter, no job store, no recipe type.

Keep this section honest as that changes. When you describe a domain feature in
any prompt file or the README before it exists, mark it `(planned)` — the
harness files all carry a "grounded in checked-in reality" clause and CI will
not catch a prose claim that runs ahead of the code.

### Naming

"InnerEye" was also a (now-archived) Microsoft medical-imaging research project.
Different domain, no conflict — but the README carries a positioning sentence so
a newcomer searching the name is not confused. Keep it there.

## Domain design (the decisions that shape every verb)

These are the load-bearing positions from the brief. Argue with them in an
issue if you have better — but do not quietly build against them.

### The three inputs — embeddings are first-class

1. **Text** — a prompt, negative prompt, params. The ordinary case.
2. **Images** — reference / init / mask / control inputs: img2img, inpainting,
   style or pose reference, last-frame-to-video.
3. **Embeddings** — an agent that already holds a vector (a CLIP text/image
   embedding, a latent, an IP-Adapter image embedding) conditions generation on
   it **directly**, without round-tripping through English.

(3) is the reason this repo is worth existing, and it is the input most backends
cannot accept. Design for it from the start rather than bolting it on.
[`embeddings-cli`](https://github.com/agentculture/embeddings-cli) and
[`embeddings-lens`](https://github.com/agentculture/embeddings-lens) are the
natural producers of those vectors — **agree an interchange format with them**
rather than inventing a private one.

### Recipes, not graphs — and not hosted-API calls either

The central tension: ComfyUI's native unit is a **workflow graph** submitted to
a queue; a hosted API's native unit is a **single request**. Model the CLI on
either one and the other backend becomes a pile of fakery.

The resolution: a portable **recipe** — `(task, inputs, params)` — that each
adapter *compiles* into its native form. The ComfyUI adapter compiles a recipe
by filling the input nodes of a **template graph** it ships (users may supply
their own graph plus a declared mapping from recipe fields to node inputs). A
hosted adapter compiles the same recipe into one HTTP request. The recipe is
backend-independent and is what gets recorded for provenance.

### Capability negotiation is mandatory

Each adapter **declares** which tasks (`text→image`, `image→image`,
`text→video`, `image→video`, `embedding→image`, …) and which input modalities it
supports. When a recipe asks for something the selected backend cannot do,
**fail honestly** — with a message naming a backend that could.

**Never silently downgrade.** Turning an embedding input into "the closest text
prompt" and generating anyway is the worst available behaviour, because the
caller cannot tell the difference from the output. Build the
capability-declaration mechanism with the *first* adapter, even though one
backend needs no negotiation; retrofitting it later means rewriting every verb.

### Generation is slow — model it as jobs

Video takes minutes; images take seconds to minutes. Agents call CLIs in loops,
so a blocking call that holds a terminal for eight minutes is a bug. ComfyUI is
already queue-shaped (submit → `prompt_id` → poll history); mirror that:
**submit / status / fetch**, with a convenience blocking-wait mode for humans.

**Job state must survive process exit** — an agent that submits in one
invocation must be able to collect in another.

### Provenance is output, not a log line

Artifacts land at predictable paths; the CLI returns those paths plus structured
metadata under `--json`. Alongside each artifact: backend, model, **seed**,
resolution, sampler/steps, the full recipe, and the exact graph if ComfyUI.
Capture seeds explicitly — never let a backend's random default go unrecorded.
A result that cannot be reproduced cannot be reviewed.

### Preview: terminals cannot show images

Decide deliberately how a preview reaches a human — an inline protocol where the
terminal supports it (sixel / kitty / iTerm), an ASCII or thumbnail fallback
where it does not, and/or handing off to
[`storybook-cli`](https://github.com/agentculture/storybook-cli) for a shareable
page. Also relevant: [`webglass-cli`](https://github.com/agentculture/webglass-cli)
(browser-side viewing) and [`media-cli`](https://github.com/agentculture/media-cli)
(the local media/device plane).

### Pluggability has to be proven

ComfyUI is first because it is local, free, and already supports all three input
modalities. It must not become the architecture. Candidates for later adapters:
local `diffusers`, a hosted API or two, a video-specific backend. Build **one**
second adapter early — even a deliberately thin one — purely to prove the
abstraction is real. Don't ship a "pluggable" claim backed by exactly one plugin.

### Non-goals (stated in the README, keep them there)

- **Not an image-understanding tool.** Reading, classifying or embedding an
  existing image belongs to `embeddings-lens`, `face-recognition-cli` and peers.
  innereye is the *output* direction.
- **Not a model zoo, trainer or fine-tuner.**
- **Not a ComfyUI reimplementation or GUI replacement** — it drives ComfyUI, it
  does not become it.
- **Not a hosting service.** Where the model runs is the operator's business.

### Suggested first slice

`innereye render --prompt "…"` against a local ComfyUI: submitted as a job,
artifact on disk, provenance JSON beside it, `--json` output, **dry-run by
default**. Then the second adapter, then image inputs, then embeddings.

## The CLI

Cited (cite-don't-import) from teken's `python-cli` reference (`teken cli cite`);
`teken` (a.k.a. `afi-cli`) is a **dev dependency only** and the runtime package
has **no third-party dependencies**. Keep it that way as long as you can — a
ComfyUI adapter speaks HTTP + JSON, which `urllib` and `json` cover; reach for a
dependency only when the domain genuinely forces it, and record why.

The agent-first rubric is enforced in CI by `teken cli doctor . --strict`.

### Structure and the contract each part holds

Three small modules are marked *stable-contract* — the rubric depends on their
exact behaviour, so changing them changes the CLI's public contract:

- **`innereye/cli/_errors.py`** — `CliError(code, message, remediation)` and the
  exit-code policy in one place: `0` success, `1` user error, `2`
  environment/setup error, `3+` reserved. Every failure raises `CliError`;
  nothing else.
- **`innereye/cli/_output.py`** — `emit_result` / `emit_error` /
  `emit_diagnostic`. The invariant agents parse against: **results to stdout,
  errors and diagnostics to stderr, never mixed**, in both text and `--json`
  mode. Text-mode errors render `error: <msg>` then `hint: <remediation>`; the
  `hint:` prefix is required by the rubric.
- **`innereye/cli/__init__.py`** — `main()` → `_build_parser()` → `_dispatch()`.
  `_dispatch` catches `CliError` and wraps *any* other exception into one, so no
  Python traceback reaches stderr. Argparse's own errors route through the same
  format via `_CliArgumentParser.error()`; parse-time errors happen before
  `args.json` exists, so `main()` pre-scans raw argv for `--json` and stashes the
  answer in the class-level `_json_hint`.

### Adding a verb or noun group

Each module under `innereye/cli/_commands/` exposes `register(sub)` that adds
its parser and calls `p.set_defaults(func=...)`. Register it in `_build_parser()`
(there is a marked spot). Handlers return `None` or an `int` exit code and raise
`CliError` on failure.

Rubric constraints worth knowing before you design a command:

- **Every command takes `--json`** — including each sub-verb of a noun group,
  since argparse will not inherit the parent's flag.
- **Any noun with action-verbs must also expose `overview`.** `cli.py` exists
  only to satisfy this and is the pattern to copy for a new noun group (note it
  passes `parser_class=type(p)` to `add_subparsers` so nested parse errors keep
  the structured error contract).
- **Descriptive verbs must not hard-fail on a missing target path.** `overview`
  accepts an optional positional `target` and ignores it, so
  `overview /no/such/path` still exits 0.
- **`learn` must stay ≥200 chars** and mention purpose, command map, exit codes,
  `--json`, and `explain`. Update its command map when you add a verb.

### Domain-verb conventions (in addition to the rubric)

- **Every write verb is dry-run by default; `--apply` commits.** Generation
  spends GPU time and writes files — a dry run should print the **compiled
  recipe** and the **resolved backend** so an agent can check itself before
  spending.
- A capability mismatch is a **user error with a named alternative**, not a
  best-effort render.
- Long work returns a **job handle**, not a blocked terminal.

### `explain`

`innereye/explain/catalog.py` is a dict keyed by command-path tuples
(`("cli", "overview")`) holding verbatim markdown; `()` and `("innereye",)` both
resolve to the root. Entries are self-contained — an agent reading one should
not need to chain reads. **Add an entry whenever you add a verb**: the lint gate
runs `teken cli doctor --strict`, which invokes `innereye explain innereye`.

### Identity resolution

`whoami.py` parses `culture.yaml` **without a YAML dependency** (line-wise,
first agent block only) to keep runtime deps empty, and finds the file by walking
up from `__file__` — deliberately *not* the caller's CWD, so the identity is
always this agent's own. A wheel install ships no `culture.yaml` alongside the
package, so `whoami` and `doctor` degrade to literal defaults rather than
failing. `whoami.find_culture_yaml` / `read_agent_fields` are reused by `doctor`,
and `whoami.report` by `overview` — keep them importable.

`doctor` checks the invariants `steward doctor` verifies — **prompt-file-present**
and **backend-consistency** — plus a skills-present check, and reports the
rubric-shaped `{healthy, checks: [{id, passed, severity, message, remediation}]}`.
It distinguishes `_PROMPT_FILE` (every prompt file *recognized* under a backend
name) from `_RESIDENT_PROMPT` (the one file the Culture daemon actually reads);
that distinction is load-bearing and `tests/test_doctor_resident_prompt.py`
guards it.

## Identity and the four harnesses

Declared in `culture.yaml`:

```yaml
agents:
- suffix: innereye
  backend: claude
```

`backend: claude` fixes the **mesh resident** prompt to `CLAUDE.md` (this file).
Changing `backend` without adding the matching prompt file breaks `doctor` and CI.

Four harnesses are live simultaneously over the same clone, each reading exactly
one root file — there is deliberately **no `AGENTS.md`**:

| Harness | File(s) |
|---------|---------|
| Claude Code | `CLAUDE.md` (this file — the fullest write-up) |
| Pi / associate | `AGENTS.override.md` + `.pi/SYSTEM.md` |
| colleague | `AGENTS.colleague.md` |
| Qwen Code | `QWEN.md` |

Two separate selections: **which binary you run** (all four always available,
no file to edit) versus **the mesh resident** `culture.yaml` declares. See
[`docs/harness-selection.md`](docs/harness-selection.md) and
[`docs/automation-contract.md`](docs/automation-contract.md) (rendered from
`docs/harness-invocations.yaml`, which CI's `harness-smoke` job reads verbatim).

**When you change what innereye *is*, change all four files.** `scripts/harness-smoke.py`
checks that each config loads; nothing checks that their prose still agrees.
The same claim also appears in three code strings — `cli/__init__.py`'s parser
`description`, `_commands/learn.py`'s `_TEXT` + `_as_json_payload()`, and
`explain/catalog.py`'s `_ROOT` — and in `README.md` and `pyproject.toml`'s
`description`. Sweep them together:

```bash
git grep -niF 'visual output surface'
```

## Commands

```bash
uv sync                                  # create .venv and install dev deps
uv run pytest -n auto                    # full suite, parallel
uv run pytest tests/test_cli.py -v       # one file
uv run pytest -k whoami -v               # one test by name
uv run pytest --cov=innereye --cov-report=term   # coverage (fails under 60%)

uv run innereye whoami                   # identity from culture.yaml
uv run innereye learn --json
uv run innereye doctor

uv run black innereye tests              # line length 100
uv run isort innereye tests              # profile=black
uv run flake8 innereye tests
uv run bandit -c pyproject.toml -r innereye
markdownlint-cli2 "**/*.md" "#node_modules" "#.local" "#.claude/skills" "#.teken"
uv run teken cli doctor . --strict       # the agent-first rubric gate CI runs
python3 scripts/scan-secrets.py          # committed-secret / non-localhost gate
uv run python scripts/harness-smoke.py --stage all --require config
```

`scan-secrets.py` also fails on **non-localhost endpoints**. A ComfyUI adapter
defaults to a local server, so keep literal addresses at `127.0.0.1` / `localhost`
and make anything else configuration, not a constant.

CI (`.github/workflows/tests.yml`) runs four jobs: `test` (pytest + SonarCloud),
`lint` (the full set above), `harness-smoke` (all four harness configs), and
`version-check`. `.github/workflows/publish.yml` is path-filtered to
`pyproject.toml` and `innereye/**`, and **both of its publish paths really
upload**:

- **push to `main`** → builds and publishes the version in `pyproject.toml` to
  **PyPI** via Trusted Publishing.
- **same-repo pull request** → rewrites the version to
  `<version>.dev<github.run_number>` and publishes that to **TestPyPI**
  (`uv publish --publish-url https://test.pypi.org/legacy/`).

The PR path is **not a dry run** — it is a real external upload of a real dev
version, and a PyPI/TestPyPI upload cannot be deleted and re-uploaded under the
same version. Fork PRs skip it (no OIDC context). Treat a version bump as
spending a version number on both indexes, not just on `main`.

**Deploy is already live** — do not repeat the brief's claim that Trusted
Publisher registration is outstanding. It was true when issue #1 was written and
is not true now: PyPI carries `innereye 0.9.0` (published by the scaffold merge)
and TestPyPI carries the PR dev builds. Verify before asserting either way:

```bash
curl -s https://pypi.org/pypi/innereye/json | python3 -c "import sys,json;print(sorted(json.load(sys.stdin)['releases']))"
```

## Conventions and workflow

- **Every PR bumps the version** — even docs/config/CI, no exceptions. Use the
  `version-bump` skill; the `version-check` CI job comments on and blocks the PR
  otherwise.
- **PRs** go through the `cicd` skill (`devex pr` + SonarCloud gating). Sign
  online posts as `- innereye (Claude)` — the `cicd` / `communicate` scripts
  resolve the nick from `culture.yaml` automatically, so do not hand-sign bodies
  those scripts author.
- **Reach for `ask-colleague` reflexively.** Treat it as the teammate at the next
  desk, not a last resort — its value is a *second, independent mind* (a
  different backend/model), not a stronger one. Before presenting or opening a PR
  on a non-trivial committed diff, run `review`; for a fresh read of an
  unfamiliar area whose answer is independent of your current context, run
  `explore`. Both are read-only (throwaway worktree, zero side effects), so the
  reflex is always safe. The side-effecting `write --apply` / `write --pr` needs
  the user's go-ahead. Colleague's output is a second opinion to verify and own,
  never authority.
- **The vendored `.claude/skills/` are cited verbatim** — do not reformat or edit
  their scripts. Re-sync from the upstream tracked in
  [`docs/skill-sources.md`](docs/skill-sources.md), which also records the live
  local divergences.
- **Tooling prerequisites:** `devex` and `agtag` (>=0.1) on PATH for the `cicd` /
  `communicate` skills; `colleague` on PATH is *optional*, needed only when
  `ask-colleague` is actually invoked.
- **Per-machine config:** copy `.claude/skills.local.yaml.example` to
  `skills.local.yaml` (git-ignored) to point skills at your sibling checkouts.
- **Cross-repo work goes through issues, not edits.** The embeddings interchange
  format, a storybook handoff, a media-cli integration — file an issue on the
  sibling with the `communicate` skill rather than editing another repo.
  **Get the user's approval on the target repo, title and body first.**
  `communicate`'s `post-issue.sh` is a thin wrapper over `agtag issue post` with
  no preview or confirmation step of its own — calling it publishes immediately,
  under this agent's identity, to a repo whose maintainers did not ask for it.
  Draft, show, then post.

### Memory discipline — recall before, remember after

The `recall` / `remember` skills are backed by the `eidetic` store. Both vendored
wrappers resolve `--scope` from `culture.yaml`'s `suffix` (→ `innereye`), so this
agent's records stay out of the global `default` scope, and both the `claude` and
`colleague` backends resolve the same suffix and therefore share them.

**Read this before your first `/remember`: the default is PUBLIC, not private.**
When the suffix resolves and you pass no `--visibility`, `remember.sh` injects
`--visibility public` — an explicit policy override, flagged as such in the
script — and a public record inside a git repo is written to
`<repo-root>/.eidetic/memory`, **committed and pushed**. `.eidetic/memory/` is
tracked here and is not in `.gitignore`. A plain `/remember` therefore publishes
to GitHub; it does not go to `$HOME`.

So:

- **`/remember --visibility private`** for anything session-derived, speculative,
  or about the operator's machine and setup. That is what routes to
  `$HOME/.eidetic/memory` and stays uncommitted.
- **Plain `/remember`** only for a durable fact you would be happy to commit and
  have teammates and mesh peers read.
- `recall.sh` defaults the same way, so a flagless `/recall` searches the public
  pool and **will not surface** private records — pass `--visibility private` to
  read those back.

Note the vendored `SKILL.md` descriptions and both scripts' own header comments
still claim a private default, contradicting the code directly below them. The
scripts are cited verbatim from guildmaster and must not be edited here; the
contradiction belongs upstream as an issue. Trust the code, not the comment.

- **`/recall` before you start** a non-trivial task — prior decisions, gotchas,
  "have we done this before?" — so you build on what is known.
- **`/remember` when something worth keeping surfaces** — a non-obvious decision
  and its rationale, a constraint, a fix and *why*, a gotcha that cost time.
  Capture it as it happens. Don't store what the repo already records (code
  structure, git history, this file, `CHANGELOG.md`); store what you would
  otherwise have to re-derive. Generation work produces exactly this kind of
  knowledge — which ComfyUI node graph actually worked, which model needs which
  VRAM, which sampler defaults are junk.

## Layout

```text
innereye/                 agent-first CLI (cited from teken's python-cli reference)
  cli/                    parser + error/output contract; _commands/ holds the verbs
  explain/                markdown catalog for `explain`, keyed by path tuple
tests/                    CLI smoke + introspection + harness-registry/config tests
scripts/                  scan-secrets.py (CI gate), harness-smoke.py (four-config check)
.claude/skills/           vendored guildmaster skill kit (cite-don't-import, verbatim)
docs/skill-sources.md     skill provenance ledger + re-sync procedure + divergences
docs/harness-*.md|.yaml   the two selections, the forced-invocation contract
culture.yaml              mesh identity (suffix + backend)
CLAUDE.md                 resident prompt (backend: claude) + this guidance
.github/workflows/        tests/lint/harness-smoke/version-check; PyPI Trusted Publishing
```
