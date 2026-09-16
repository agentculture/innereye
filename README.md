# innereye

**Visual output surface for agents** — render and preview images and videos from
**text, image, or embedding** inputs. Starts with a ComfyUI backend but is not
locked to it: pluggable generation backends behind one agent-first CLI.

Agents can reason about images but cannot produce them. `innereye` closes that
gap: it turns a request for a picture or a video into an actual artifact on
disk, with enough provenance that the result can be reproduced or explained.

> **Not the Microsoft project.** "InnerEye" was also a (now-archived) Microsoft
> Research effort in *medical imaging analysis*. This is an unrelated project in
> a different domain — image/video **generation** for AI agents, in the
> [AgentCulture](https://github.com/agentculture) mesh.

## Status

**Implemented.** `innereye render` compiles a portable recipe into an
operator-supplied ComfyUI template graph, submits it as a job, and `innereye job
fetch` writes the artifact plus a provenance sidecar; `--preview` shows it in
the terminal. Verified end to end on a DGX Spark (GB10): FLUX.1-dev produced a
1024x1024 PNG in ~47s, and the same seed reproduced a **byte-identical** file.

Still `(planned)`: a second backend adapter, and **embedding inputs** — no
shipped template graph exposes an embedding node, so `embedding_to_image` is
declared *unsupported* and refused rather than approximated.

The design is below and in
[issue #1](https://github.com/agentculture/innereye/issues/1);
[`CLAUDE.md`](CLAUDE.md) is the working write-up.

> **ComfyUI has no authentication.** It ships no authn/authz of any kind, and
> NVIDIA's playbook `launch.sh` runs `--listen 0.0.0.0`, which binds every
> interface — exposing the GPU, every prior prompt via `/history`, and every
> output via `/view` to anyone on the network. innereye defaults to
> `http://127.0.0.1:8188` and you should launch ComfyUI with
> `--listen 127.0.0.1` unless you have deliberately decided otherwise.

## The three inputs

1. **Text** — a prompt, negative prompt, params. The ordinary case.
2. **Images** — reference / init / mask / control inputs: img2img, inpainting,
   style or pose reference, last-frame-to-video.
3. **Embeddings** — an agent that already holds a vector (a CLIP text/image
   embedding, a latent, an IP-Adapter image embedding) conditions generation on
   it **directly**, without round-tripping through English.

(3) is the distinguishing requirement, and the input most backends cannot
accept. Sibling projects
[`embeddings-cli`](https://github.com/agentculture/embeddings-cli) and
[`embeddings-lens`](https://github.com/agentculture/embeddings-lens) are the
natural producers of those vectors.

## Design commitments

- **Backend-independent recipes.** A portable `(task, inputs, params)` recipe is
  what you write and what gets recorded; each adapter *compiles* it into its
  native form — a filled ComfyUI template graph, or a single HTTP request for a
  hosted API. ComfyUI is first because it is local, free and already supports
  all three input modalities; it does not get to become the architecture.
- **Honest capability negotiation.** Every adapter declares the tasks
  (`text→image`, `image→image`, `text→video`, `image→video`, `embedding→image`,
  …) and input modalities it supports. Ask for something a backend cannot do and
  it **fails with a message naming a backend that could**. It never silently
  downgrades — turning an embedding into "the closest text prompt" and
  generating anyway would be indistinguishable in the output.
- **Generation is modelled as jobs.** Submit / status / fetch, with a blocking
  wait for humans. Job state survives process exit, so an agent can submit in
  one invocation and collect in another.
- **Provenance is part of the output.** Backend, model, seed, resolution,
  sampler/steps, the full recipe, and the exact graph where applicable — beside
  the artifact, not in a log line. Seeds are captured explicitly.
- **Preview is a real problem, not an afterthought.** Terminals cannot show
  images; a preview reaches a human through an inline protocol where the
  terminal supports one, a fallback where it does not, or a handoff to
  [`storybook-cli`](https://github.com/agentculture/storybook-cli).
- **Dry-run by default.** Generation spends GPU time and writes files, so every
  write verb prints the compiled recipe and the resolved backend unless you pass
  `--apply`.

## Non-goals

- **Not an image-understanding tool.** Reading, classifying or embedding an
  *existing* image belongs to `embeddings-lens`, `face-recognition-cli` and
  peers. innereye is the **output** direction.
- **Not a model zoo, trainer or fine-tuner.**
- **Not a ComfyUI reimplementation or GUI replacement** — it drives ComfyUI, it
  does not become it.
- **Not a hosting service.** Where the model runs is the operator's business.

## Quickstart

```bash
uv sync
uv run pytest -n auto                 # run the test suite
uv run innereye whoami                # identity from culture.yaml
uv run innereye learn                 # self-teaching prompt (add --json)
uv run teken cli doctor . --strict    # the agent-first rubric gate CI runs
```

## CLI

| Verb | What it does |
|------|--------------|
| `whoami` | Report this agent's nick, version, backend, and model from `culture.yaml`. |
| `learn` | Print a structured self-teaching prompt. |
| `explain <path>` | Markdown docs for any noun/verb path. |
| `overview` | Read-only descriptive snapshot of the agent. |
| `doctor` | Check the agent-identity invariants (prompt-file-present, backend-consistency). |
| `cli overview` | Describe the CLI surface itself. |

Every command supports `--json`. Results go to stdout, errors/diagnostics to
stderr (never mixed). Exit codes: `0` success, `1` user error, `2` environment
error, `3+` reserved. The CLI is cited (cite-don't-import) from
[teken](https://github.com/agentculture/teken)'s `python-cli` reference, so the
runtime package has **no third-party dependencies**.

## Repository conventions

- **A mesh identity** — `culture.yaml` (`suffix: innereye`, `backend: claude`)
  and the matching resident prompt file, `CLAUDE.md`. The mesh resident is one
  of **two separate selections** over this clone — see
  [Two selections, not one](#two-selections-not-one) below.
- **Four harness prompt files**, one per agent harness, each read by exactly one
  of them (see [Prompt files by harness](#prompt-files-by-harness)). All four
  harnesses are usable interactively regardless of which one `culture.yaml`
  names as the mesh resident.
- **The canonical guildmaster skill kit** under `.claude/skills/`, vendored
  cite-don't-import. See [`docs/skill-sources.md`](docs/skill-sources.md).
- **A build + deploy baseline** — pytest, lint, the agent-first rubric gate, a
  committed-secret scan, a four-harness config smoke check, and PyPI Trusted
  Publishing, all wired into GitHub Actions.
- **Every PR bumps the version** (`version-bump` skill) — even docs and CI. The
  `version-check` job blocks merge otherwise.

## Prompt files by harness

Four harnesses, four root files, no shared base — each file is read by
exactly one harness:

| Harness | File(s) |
|---------|---------|
| Claude Code | [`CLAUDE.md`](CLAUDE.md) |
| Pi / associate | [`AGENTS.override.md`](AGENTS.override.md) + [`.pi/SYSTEM.md`](.pi/SYSTEM.md) |
| colleague | [`AGENTS.colleague.md`](AGENTS.colleague.md) |
| Qwen Code | [`QWEN.md`](QWEN.md) |

**Claude Code** — `CLAUDE.md` is the fullest write-up of the repo's design and
conventions; read it first.

**Pi / associate** — `AGENTS.override.md` replaces this directory's
`AGENTS.md`/`CLAUDE.md` in Pi's context layer, so Pi does not inherit
`CLAUDE.md`. `.pi/SYSTEM.md` replaces Pi's default system prompt with the
non-coding `associate` identity (read/find/summarize only).

**colleague** — colleague's prompt cascade is `AGENTS.md` →
`AGENTS.colleague.md` → `AGENTS.colleague.<model>.md`. This repo ships only
the middle layer: there is no `AGENTS.md` (a shared base across harnesses was
considered and rejected) and no per-model override file.

**Qwen Code** — Qwen Code reads `QWEN.md` and `AGENTS.md`; since there is no
`AGENTS.md`, `QWEN.md` is its sole source of guidance.

There is intentionally **no `AGENTS.md`** at the root — each harness gets an
unrelated file rather than cascading from a shared base.

## Two selections, not one

It is tempting to read "switch harness" as one decision. It is actually two:

1. **The interactive harness** — which binary you run (`claude`, `pi`,
   `colleague`, `qwen`). `cd` into the clone and run any of them; all four
   are live simultaneously, and none of them requires editing a file or
   flipping a switch. A harness can be force-selected for one invocation
   (e.g. a CI smoke check) without ever touching `culture.yaml` — see
   [`docs/automation-contract.md`](docs/automation-contract.md).
2. **The mesh resident** — the single `backend` `culture.yaml` declares,
   which is what the Culture daemon starts and what `steward doctor`
   checks. `guild harness use <name>` changes only this.

`culture.yaml`'s `backend` affects (2) only. It never affects which harness
you can invoke interactively in (1). See
[`docs/harness-selection.md`](docs/harness-selection.md) for the full writeup.

## Contributing

Read [`CLAUDE.md`](CLAUDE.md) first — it carries the domain design, the CLI's
stable contracts, and the workflow conventions (version-bump-every-PR, the
`cicd` PR lane, deploy setup). Design disagreement is welcome on
[issue #1](https://github.com/agentculture/innereye/issues/1); the brief there
is a starting position, not a spec.

Copy `.claude/skills.local.yaml.example` to `skills.local.yaml` (git-ignored) to
point the vendored skills at your local sibling checkouts.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
