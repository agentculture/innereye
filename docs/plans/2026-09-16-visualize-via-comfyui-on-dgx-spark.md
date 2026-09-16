# Build Plan — visualize via ComfyUI on DGX Spark

slug: `visualize-via-comfyui-on-dgx-spark` · status: `exported` · from frame: `visualize-via-comfyui-on-dgx-spark`

> innereye render turns a prompt into an actual picture on a DGX Spark: submitted as a job to a local ComfyUI, artifact and provenance JSON on disk, and a preview you can actually see in the terminal.

## Tasks

### t1 — recipe type and the operator-supplied graph+mapping contract

- instruction: start from the 8 playbook graphs already analysed in the spec. Node ids are NOT stable across graphs, so the mapping is part of the contract, not an inference. Keep this module free of any HTTP or ComfyUI import — it is the portable layer.
- covers: c3, h8, c20, h15, c21, h16, c23, h18, c25, h24
- acceptance:
  - innereye/recipe.py defines a backend-independent Recipe(task, inputs, params) covering both image and video tasks with one compile path
  - a GraphMapping maps recipe fields to node input paths; compiling the same recipe against flux-text-to-image and hidream-text-to-image lands identical fields on different node ids
  - a graph supplied without a mapping is refused with a non-zero exit naming what is missing; innereye never guesses node ids
  - length and fps are ordinary recipe params, not a video-specific branch

### t2 — stdlib-only HTTP transport with a scheme guard

- instruction: multipart upload is the one place a dependency might tempt you — hand-roll it with the stdlib and record why if you cannot. Verified live: POST /upload/image returns {name, subfolder, type}.
- covers: c10, h11, c13, h22
- acceptance:
  - innereye/backends/`_http.py` performs GET/POST-JSON/multipart-upload/byte-download using only urllib.request and json; pyproject dependencies stays \[\]
  - urlopen is wrapped by an explicit http/https scheme guard so bandit B310 passes without a blanket nosec
  - no artifact bytes pass through `_output.py`; the transport returns bytes and the caller writes files
  - a transport pointed at an unreachable server raises CliError with an environment exit code, never a traceback

### t3 — capability declaration and honest-refusal negotiation

- instruction: build the negotiation mechanism NOW even though one backend needs no negotiation — retrofitting it later means rewriting every verb. The embedding refusal test must exist before any embedding support does.
- covers: c5, h19, c9, h20
- acceptance:
  - innereye/backends/`__init__.py` defines an adapter protocol where each adapter DECLARES its supported tasks and input modalities
  - embedding-to-image is declared unsupported from day one and a recipe requesting it fails with a non-zero exit naming a backend that could, never a text-prompt downgrade
  - no model name, graph filename or resolution appears as a constant anywhere in innereye

### t4 — versioned, concurrency-safe job store that survives process exit

- instruction: this is innereye's FIRST on-disk format — the challenge pass flagged that the next change inherits a migration problem if it ships without a version field. ComfyUI's queue is a second store that can disagree after a restart; reconcile explicitly.
- covers: c28, h4, c40, h32
- acceptance:
  - innereye/jobs.py declares where the store lives and writes a `schema_version` field from the first release
  - a job submitted by one process is collectable by a separate later process; killing the submitter between submit and fetch does not lose the job
  - two concurrent submits produce two distinct, both-collectable records
  - a job whose `prompt_id` the server no longer knows reports a distinct recoverable state rather than hanging or crashing
  - the store is safe under pytest -n auto

### t5 — provenance sidecar and collision-safe artifact paths

- instruction: the challenge pass found that predictable-paths plus seed-naming silently overwrites the evidence the reproducibility claim depends on. Collision safety is the fix. Also note ComfyUI already embeds the prompt in PNG text chunks and WebP EXIF — document that artifacts are self-disclosing when shared.
- covers: c29, h5, c39, h31, c38, h30
- acceptance:
  - innereye/provenance.py writes a sidecar carrying backend, model, seed, resolution, sampler, steps, container and the full recipe
  - the seed is chosen by innereye and asserted present in the SUBMITTED graph payload, not read back from a backend default
  - a write that would land on an existing artifact or sidecar refuses with a non-zero exit unless an explicit overwrite flag is passed; rendering the same recipe and seed twice does not destroy the first result
  - the container (webp for video, png for image) is recorded explicitly

### t6 — terminal preview with kitty protocol and an honest fallback

- instruction: ghostty is the local target and implements kitty graphics. Detect capability, do not assume it. The fallback path must be exercised in tests, not just present.
- covers: c8, h10
- acceptance:
  - innereye/preview.py renders an artifact inline via the kitty graphics protocol where the terminal supports it
  - under TERM=dumb or a non-supporting terminal it falls back to an ASCII or thumbnail rendering and says which it used
  - preview never prints only a path and calls it a preview

### t7 — ComfyUI adapter: compile, submit, poll, cancel, collect

- instruction: all of this was verified live against 127.0.0.1:8188 running ComfyUI 0.33.2 — see the spec's Scope exploration entries for the exact responses. Do NOT reimplement weight validation: the server already fails closed at submit with a better error than you can construct. Document that ComfyUI keeps its own auto-incrementing copy under its output dir that innereye does not clean.
- depends on: t1, t2, t3
- covers: c2, h7, c4, h9, c31, h25, c34, h26, c35, h27, c37, h29
- acceptance:
  - innereye/backends/comfyui.py compiles a Recipe into a template graph and submits it via POST /prompt
  - the job model targets /api/jobs first and falls back to /history only when that endpoint 404s; all five states round-trip: pending, `in_progress`, completed, failed, cancelled
  - cancel is wired to POST /api/jobs/{id}/cancel and failed carries the server error text out as a non-zero exit
  - a graph naming absent weights surfaces ComfyUI's `node_errors` payload (`input_name`, `received_value`, valid list) as CliError.remediation without a client-side /`object_info` pre-flight
  - image inputs POST /upload/image first and feed the returned name to LoadImage
  - everything goes over HTTP; the adapter never reads ComfyUI's output or models directory from the local filesystem, so a remote server works unchanged

### t8 — render verb, dry-run by default, with the demo graph seam

- instruction: the demo seam fetches the NVIDIA playbook graph, which needs tier-1 FLUX weights — document that prerequisite. Keep the demo visibly distinct from the operator-supplied path so nobody ships a pipeline silently depending on raw.githubusercontent.com.
- depends on: t7, t5, t6
- covers: c22, h17
- acceptance:
  - innereye render is dry-run by default and prints the compiled recipe and resolved backend; --apply commits
  - a dry run spends zero GPU seconds and makes no submission
  - omitting --graph produces an honest error naming how to obtain one; it never falls back to a bundled or downloaded default
  - the demo download seam is a separately named invocation, and the default path never touches the network
  - render takes --json and --preview

### t9 — job noun group: submit, status, fetch, cancel, overview

- instruction: the rubric is only enforced by teken cli doctor --strict, not by pytest — run it before opening the PR, not after. `_dispatch` gives you no timeout or signal plumbing, so --wait owns its own SIGINT handling.
- depends on: t4, t7
- covers: c12, h12
- acceptance:
  - innereye/cli/`_commands`/job.py registers a two-level noun group copying cli.py's `parser_class`=type(p) pattern
  - every level declares its own --json, including each sub-verb
  - job overview exists, because a noun with action-verbs must expose one
  - uv run teken cli doctor . --strict passes
  - long work returns a job handle; a --wait mode emits progress on stderr and exactly one payload on stdout

### t10 — fixtures and the committed-JSON secrets gate

- instruction: verified: the endpoint gate only parses files that are valid JSON and only inspects those four key names, so markdown and Python are unaffected — but a committed graph or /history fixture is exactly the JSON case. Run scan-secrets on fixture paths as you write them.
- depends on: t7
- covers: c11, h21
- acceptance:
  - any template graph or recorded ComfyUI response committed as a test fixture passes python3 scripts/scan-secrets.py
  - no fixture carries a non-local url/host/endpoint/baseUrl key
  - the ComfyUI HTTP layer is mocked in tests; no test requires a live server, and none binds a fixed port under pytest -n auto

### t11 — register the verbs and sweep the in-repo enumerations in lockstep

- instruction: three code modules carry hand-maintained verb enumerations and two carry a status string that a render verb makes false. Nothing in pytest catches an unregistered verb today — that is why the generic introspection test is an acceptance criterion here, not a nice-to-have.
- depends on: t8, t9
- covers: c15, h13, c26, h2, c27, h3
- acceptance:
  - cli/`__init__.py` registers render and job at the marked spot; learn.py's `_TEXT` command map AND `_as_json_payload` commands list both gain them
  - learn.py's literal status string 'scaffold: no generation verb implemented yet' is gone, and learn stays over 200 chars mentioning purpose, command map, exit codes, --json and explain
  - explain/catalog.py gains entries for render and job, and `_ROOT`'s ## Verbs list and scaffold line are updated
  - overview.py's `_VERBS` list includes the new verbs
  - a NEW generic test walks the registered argparse tree and asserts every command has a catalog entry and a --json flag — the gap the challenge pass found
  - all five edits land in the SAME commit, so no intermediate commit ships a CLI whose learn output contradicts its own command surface

### t12 — sweep the five prose surfaces and state the ComfyUI exposure

- instruction: nothing in CI checks prose agreement — harness-smoke verifies file presence and registry wiring only. Read the five edited passages side by side by hand. git grep -niF 'visual output surface' is the sweep command.
- depends on: t11
- covers: c17, h14, c36, h28
- acceptance:
  - README.md:18, CLAUDE.md:20, AGENTS.override.md:29, AGENTS.colleague.md:38 and QWEN.md:19 no longer claim there is no render verb; .pi/SYSTEM.md is untouched
  - the five edited passages agree with each other, not merely each with the code
  - the 13 'visual output surface' occurrences remain consistent
  - every documented endpoint and example defaults to 127.0.0.1, and wherever innereye tells an operator to launch ComfyUI it states the server has no authentication and that --listen 0.0.0.0 exposes the GPU and all prior prompts to the LAN
  - anything still unbuilt (embeddings, a second adapter) is marked (planned)

### t13 — version bump, changelog, and the deliberate index spend

- instruction: publish.yml is path-filtered to innereye/\*\* so the first adapter commit triggers a REAL TestPyPI upload of `<version>.dev<run_number>`, and merge publishes to PyPI. A version number is spent on both indexes irreversibly — accept that deliberately at commit time, not discover it at PR time.
- depends on: t12
- covers: c19, h23
- acceptance:
  - the version is bumped in the SAME commit that first adds a file under innereye/, via the version-bump skill
  - CHANGELOG.md gains a Keep-a-Changelog entry documenting the new verbs and the retraction of the five scaffold claims
  - the version-check CI job passes

### t14 — live acceptance: one image and one video against the running server

- instruction: byte-identical reproduction may simply not hold on this hardware — run the same recipe twice and hash both artifacts BEFORE committing to that success signal. If it fails, reword the claim with the evidence rather than quietly dropping it.
- depends on: t13
- covers: c1, h1, c30, h6
- acceptance:
  - one image render and one video render both produce artifacts against ComfyUI on 127.0.0.1:8188 with tier-1 weights — the video half is NOT deferred
  - the preview renders a visible picture in ghostty; the acceptance is a visible image, not a successful HTTP 200
  - re-running a recorded provenance JSON reproduces a byte-identical artifact over at least 1 repeat run, OR the success signal is reworded with evidence that sampler/cuDNN non-determinism makes byte-identity unachievable on GB10
  - a dry run prints the compiled recipe and resolved backend in under 1 second having spent 0 GPU seconds
  - a capability mismatch exits non-zero naming an alternative backend

## Risks

- [out_of_scope] embedding-to-image needs custom ComfyUI nodes (unCLIP / IPAdapter) that no playbook graph provides; the capability mechanism must accept it later without rewriting every verb
- [unknown_nonblocking] the exit-code policy reserves 3+ but defines nothing, so backend-unreachable lands as 2 (environment); whether to spend a new code is undecided and affects every adapter error path
- [unknown_nonblocking] per-step progress for --wait is websocket-only in ComfyUI, which the stdlib-only rule makes expensive; polling /api/jobs gives state transitions but not progress
- [unknown_nonblocking] t14 cannot run until the tier-1 weights finish downloading; the FLUX VAE also depends on a license acceptance that is done but untested end-to-end (task t14)
