---
name: innereye
type: command
description: >
  Render and preview images and videos from a text prompt or an input image —
  the mesh's visual output surface. Agents can reason about pictures but cannot
  produce them; innereye closes that gap by compiling a portable recipe into an
  operator-supplied ComfyUI template graph, submitting it as a job, and writing
  the artifact to disk with enough provenance to reproduce it. Use when the user
  or a peer agent says "make me an image", "generate a picture", "render this",
  "visualize this", "make a short clip/video", "show me what X looks like", or
  when a task needs a visual artifact rather than a description of one. Also
  covers following up a submitted render: "is my render done", "fetch that job",
  "cancel that render". NOT for reading, classifying or embedding an existing
  image — that is the input direction and belongs to `embeddings-lens` and
  `face-recognition-cli`; innereye is the output direction only.
---

# innereye — make an actual picture, not a description of one

The skill is named **`innereye`**; it drives the `innereye` CLI. One sentence:
**render and preview images and videos from text or image inputs — starting with
ComfyUI, but not locked to it.**

Two things are worth knowing before the first command, because both surprise
people:

1. **Nothing renders until you pass `--apply`.** Every write verb is dry-run by
   default. A bare `render` prints the compiled recipe and the resolved backend
   and exits, having spent nothing. This is deliberate: generation costs GPU
   time, and an agent in a loop should be able to check itself first.
2. **You supply the template graph, and it is a *pair*.** innereye ships no
   default graph and will never silently pick one. Node ids are not stable
   across graphs — flux saves at node `9`, hidream at `12` — so a graph is
   uncompilable without a mapping from recipe fields to node input paths.

## Prerequisites — innereye does not provision anything

innereye drives a generation backend; it does not install one. Before any render
works you need:

- **A running ComfyUI**, reachable over HTTP. innereye defaults to
  `http://127.0.0.1:8188`.
- **Weights that match your graph.** This is the most common failure. A graph
  naming `flux1-dev.safetensors` needs that file present on the *server*.

> **ComfyUI ships no authentication of any kind.** NVIDIA's playbook
> `launch.sh` runs `--listen 0.0.0.0`, which binds every interface — exposing
> the GPU, every prior prompt via `/history`, and every output via `/view` to
> anyone on the network. Launch with `--listen 127.0.0.1` unless you have
> deliberately decided otherwise, and never tell an operator to bind `0.0.0.0`
> without saying what it exposes.

If ComfyUI is not running, innereye exits `2` (environment error) with the curl
command to check it. That is the expected first error, not a bug.

## How to run

```bash
bash .claude/skills/innereye/scripts/innereye.sh <verb> [args...]
```

The wrapper resolves the CLI portably — an installed `innereye` on `PATH` (the
normal mesh case), falling back to `uv run innereye` inside the checkout. Every
verb is forwarded verbatim, so `innereye <verb>` works identically when the tool
is installed. If neither resolves: `uv tool install innereye`.

**Before doing anything else, let the CLI teach you.** innereye is agent-first
by design and its own introspection is authoritative where this file and the
code ever disagree:

```bash
innereye learn --json        # purpose, command map, exit codes, --json contract
innereye explain render      # the graph+mapping contract, the demo seam
innereye explain job         # job states, the store, collision safety
```

## The shortest path to a picture

If you have no graph yet, fetch a demo pair. `--demo` is a **separately named
mode**: it is the only path that touches the network, and the ordinary render
path never does.

```bash
innereye render --demo flux-text-to-image --into graphs/
```

That writes `graphs/flux-text-to-image.api.json` plus a matching
`.mapping.json`. It downloads the **graph, not the weights** — the flux demo
needs NVIDIA's playbook tier-1 set (~35 GB) on the server.

Then:

```bash
# 1. dry run first — free, instant, submits nothing
innereye render --prompt "a snow leopard on a cliff at golden hour" \
  --graph graphs/flux-text-to-image.api.json --width 1024 --height 1024 --steps 20

# 2. commit
innereye render --prompt "a snow leopard on a cliff at golden hour" \
  --graph graphs/flux-text-to-image.api.json --width 1024 --height 1024 --steps 20 \
  --out renders --apply --wait --preview
```

`--wait` blocks until the job finishes and then fetches. Without it you get a
job handle back immediately — which is usually what an agent wants.

## Verbs

| Command | What it does |
|---------|--------------|
| `render --prompt … --graph …` | Compile a recipe and print it. **Dry run** — nothing submitted. |
| `render … --apply` | Submit as a job; returns a job handle. |
| `render … --apply --wait [--preview]` | Submit, block, fetch, optionally show it. |
| `render --demo <name> [--into DIR]` | Download a demo graph + mapping. The only networked path. |
| `job overview` | The store, the states, and every known job. |
| `job status <id>` | Where one job stands. |
| `job fetch <id> [--preview]` | Download artifacts + write provenance. |
| `job cancel <id>` | Stop a queued or running job. |

Every command — including each `job` sub-verb — takes `--json`. Results go to
**stdout**, diagnostics and errors to **stderr**, never mixed. In `--json` mode
stdout is exactly one payload, so it is safe to pipe into `jq`.

Exit codes: `0` success, `1` user error, `2` environment/setup error.

## Jobs, because generation is slow

Video takes minutes; images take seconds to minutes. An agent calling a CLI in a
loop must not block a terminal for eight minutes, so innereye mirrors ComfyUI's
own shape: **submit → status → fetch**.

**Job state survives process exit.** A job submitted in one invocation is
collectable in another — that is the point. States are `pending`,
`in_progress`, `completed`, `failed`, `cancelled`, plus innereye's own
`unknown` for a job the store remembers that the backend no longer recognises
(restarting ComfyUI invalidates its queue ids).

## What you get back

Every artifact lands at a predictable path with a **provenance sidecar** beside
it recording backend, model, **seed**, container, resolution, sampler, steps and
the full recipe. The seed is chosen by innereye *before* submission and asserted
present in the submitted graph, so it is never a backend default read back after
the fact. On a DGX Spark, re-running a recorded seed reproduced a
**byte-identical** file.

Two things to tell a user about artifacts:

- **Writes refuse to clobber.** A second render landing on an existing artifact
  or sidecar exits non-zero unless `--overwrite` is passed. Overwriting would
  destroy the earlier result's provenance, which is the evidence the whole
  reproducibility story rests on.
- **Artifacts are self-disclosing.** ComfyUI embeds the full prompt graph into
  what it saves — PNG text chunks for stills, EXIF for animated WebP. Sharing a
  render shares its prompt and its entire graph. Say so before posting one
  somewhere public.

**Video lands as `.webp`.** The playbook's video graphs end in
`SaveAnimatedWEBP`, so that is what is written, and the container is recorded in
the sidecar. It is a real animated image, not an mp4 — do not describe it as one.

## Preview — terminals cannot show images

`--preview` picks the best available path and **says which one it used**:
inline graphics where the terminal supports the kitty protocol (ghostty, kitty),
an ASCII rendering where it does not, and an explicit description where the
bytes cannot be decoded at all (animated WebP, for instance).

It never prints only a path and calls it a preview. If you are relaying a result
to a human who cannot see your terminal, send them the file.

## Hard rules (do not violate)

- **Never silently downgrade.** Adapters *declare* which tasks and input
  modalities they support. When a recipe asks for something the backend cannot
  do, innereye fails with a non-zero exit naming a backend that could — or
  saying plainly that none does. If innereye refuses, **relay the refusal**;
  do not rewrite the request into something it will accept and present the
  result as what was asked for. Turning an embedding input into "the closest
  text prompt" is the worst available behaviour, because the caller cannot tell
  the difference from the output.
- **Embeddings are not supported yet.** `embedding_to_image` is declared
  unsupported and refused on purpose. It is the modality innereye exists for
  long-term, but no shipped template graph exposes an embedding node, so
  claiming it would be a lie. Do not work around the refusal.
- **Dry-run first when spending matters.** Especially for video, and especially
  in a loop. Show the compiled recipe before `--apply`.
- **Do not invent node ids.** If a mapping is missing a field, innereye says
  which field and refuses. Fix the mapping; never guess a node id, and never
  hand-edit an operator's graph to make something fit.
- **Report failures as failures.** A `failed` job carries the server's error
  text out. Pass it along rather than retrying silently.
- **Provisioning is the operator's business.** Do not download 70 GB of weights
  or start a server on someone's machine without being asked.

## Troubleshooting

| Symptom | What it means |
|---------|---------------|
| exit `2`, "cannot reach backend" | ComfyUI is not running, or the endpoint is wrong. |
| "Prompt outputs failed validation" naming a `*_name` input | The graph names weights the **server** does not have. The message lists the valid values verbatim — that is ComfyUI's own check, and it is better than anything innereye could reconstruct. |
| "no graph mapping found" | You passed `--graph` without its mapping. They travel together. |
| "graph mapping does not place: params.X" | The mapping has no node path for a field you set. Add it, or drop the flag. |
| "refusing to overwrite" | A prior artifact is there. Change `--out`, change the seed, or pass `--overwrite` deliberately. |
| "is not an API-format ComfyUI graph" | You exported the UI format. Use **Save (API Format)**. |

## Non-goals

- **Not an image-understanding tool.** Reading, classifying or embedding an
  *existing* image belongs to `embeddings-lens` and peers. innereye is the
  **output** direction.
- **Not a model zoo, trainer or fine-tuner.**
- **Not a ComfyUI reimplementation or GUI replacement** — it drives ComfyUI, it
  does not become it.
- **Not a hosting service.** Where the model runs is the operator's business.

## Provenance

This is a **first-party** skill — its origin is
[`agentculture/innereye`](https://github.com/agentculture/innereye), authored
alongside the CLI it operates (dogfooding). It is the *inverse* of the other
skills under `.claude/skills/`, which innereye vendors **from** guildmaster.
guildmaster pulls this skill **from** innereye and broadcasts it to the rest of
the AgentCulture mesh; because innereye is upstream, it is **never re-vendored
back** from guildmaster's re-broadcast copy. The `cite, don't import` policy
still holds: downstream repos copy it, they don't symlink or depend on it. See
[`docs/skill-sources.md`](../../../docs/skill-sources.md).
