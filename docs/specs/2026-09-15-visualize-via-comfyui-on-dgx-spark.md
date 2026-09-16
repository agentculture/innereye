# visualize via ComfyUI on DGX Spark

> innereye render turns a prompt into an actual picture on a DGX Spark: submitted as a job to a local ComfyUI, artifact and provenance JSON on disk, and a preview you can actually see in the terminal.
> instruction: run the full path on the DGX Spark once ComfyUI is up; the acceptance is a visible picture, not a successful HTTP 200

## Audience

- an agent on the mesh that needs a picture or a clip and cannot produce one, plus the human operator who provisioned ComfyUI on the DGX Spark and wants to see the result without leaving the terminal
  - instruction: diff the two output modes for the same render and confirm neither is a second-class citizen

## Before → After

- Before: agents can reason about images but cannot make one. innereye on disk today is six introspection verbs (whoami, learn, explain, overview, doctor, cli overview) and nothing else — a request for a picture dead-ends, and five root prompt files say so in as many words
  - instruction: re-run uv run innereye --help and the git grep before writing the PR description
- After: innereye render --prompt TEXT --graph PATH submits a job to a local ComfyUI and returns a handle; innereye job fetch ID writes an image or a video artifact to a predictable path with a provenance JSON beside it; a preview flag draws it inline where the terminal supports it
  - instruction: kill the submitting process between submit and fetch and confirm fetch still works

## Why it matters

- the mesh gets a visual artifact that is reproducible rather than merely described: seed, graph, model, sampler and the full recipe are recorded at generation time, so any result can be re-run, diffed or reviewed instead of taken on trust
  - instruction: assert the seed appears in the submitted graph payload, not only in the response

## Requirements

- the ComfyUI adapter's template graphs already exist upstream: NVIDIA's dgx-spark-playbooks ships 8 API-format graphs under nvidia/playbook-comfyui/assets/`workflow_api`/ (flux-text-to-image, hidream-text-to-image, flux-controlnet, wan-text-to-video, wan-image-to-video, hunyuan-1080p-video, cosmos-video2world, flux-to-wan-pipeline) — innereye cites these as its shipped templates rather than authoring graphs from scratch
  - instruction: re-fetch the `workflow_api` directory listing at implementation time; upstream is a main branch and can move
  - honesty: the 8 playbook graphs still exist at that path and still load against the pinned ComfyUI v0.33.2 the playbook installs
- a recipe compiles into the playbook's flux-text-to-image.api.json by overwriting named node inputs: node 6 CLIPTextEncode.text (prompt), 25 RandomNoise.`noise_seed` (seed), 27 EmptySD3LatentImage.width/height, 17 BasicScheduler.steps, 16 KSamplerSelect.`sampler_name`, 9 SaveImage.`filename_prefix` — every provenance field CLAUDE.md demands is an explicit graph input, so nothing has to be inferred after the fact
  - instruction: compile the same recipe against both graphs and assert the same recipe fields land on different node ids
  - honesty: the node-input mapping holds for a graph innereye did not author — test it against hidream as well as flux, since node ids differ
- the image-input modality has a working path but needs a second endpoint: wan-image-to-video.api.json node 52 is LoadImage {"image": "`input_image`.png"} — a server-side FILENAME, not bytes, so the ComfyUI adapter must POST /upload/image before /prompt. Any img2img/control/last-frame recipe inherits this two-step submit
  - instruction: verify against a running server before designing the adapter interface around it
  - honesty: POST /upload/image is actually how ComfyUI v0.33.2 accepts an image, and the returned filename is what LoadImage expects
- terminal preview has a concrete target here: `TERM_PROGRAM`=ghostty, which implements the kitty graphics protocol — so 'visualize' can mean a real inline image on this machine, with an ASCII/thumbnail fallback elsewhere, exactly as CLAUDE.md's Preview section anticipates
  - instruction: test inline preview in ghostty and the fallback under TERM=dumb
  - honesty: ghostty renders the kitty graphics protocol for the artifact sizes this produces, and the fallback path is exercised on a terminal that does not
- the ComfyUI adapter stays stdlib-only: pyproject.toml line 16 is dependencies = \[\], and the ComfyUI API is HTTP+JSON (POST /prompt, `GET /history/<id>`, GET /view, POST /upload/image) which urllib.request and json cover. Expect a bandit B310 finding on urlopen — B310 is NOT in pyproject.toml bandit skips (only B101/B404/B603) — so scheme-guarded code or a justified nosec is part of the slice
  - instruction: if multipart forces a dependency, record why rather than quietly adding one
  - honesty: urllib covers every call the adapter needs including the multipart upload for images, without reaching for a dependency
- the CLI core absorbs a render/job verb without modification: `_build_parser`() has a literal 'Register your own noun groups here' spot (cli/`__init__.py`:88-96), and cli.py's `add_subparsers`(dest=..., `parser_class`=type(p)) at cli.py:40 is the copyable two-level template. Every subparser level must declare its own --json; the class-level `_CliArgumentParser`.`_json_hint` pre-scan only affects argparse-time error rendering
  - instruction: run uv run teken cli doctor . --strict before opening the PR, not after
  - honesty: the new verb passes teken cli doctor . --strict, which is the only place the agent-first rubric is actually enforced
- a render verb forces five in-repo edits in lockstep: learn.py's `_TEXT` command map (30-37) AND `_as_json_payload`()'s commands list plus its literal status string 'scaffold: no generation verb implemented yet' (65-73); explain/catalog.py's ENTRIES plus `_ROOT`'s ## Verbs list and its scaffold line (27-39); overview.py's `_VERBS` (27-33); a new hand-written test pair; and a CHANGELOG entry with a version bump
  - instruction: grep the five sites in the diff before pushing
  - honesty: all five edits land in the same commit as the verb, so no intermediate commit ships a CLI whose learn output contradicts its own command surface
- the prose blast radius is five files with a near-verbatim false sentence: README.md:18-20, CLAUDE.md:20-25, AGENTS.override.md:29-33, AGENTS.colleague.md:38-41 and QWEN.md:19-22 each say 'no render verb, no backend adapter, no job store'. .pi/SYSTEM.md is the one root prompt file with NO domain prose and stays untouched. Plus 13 'visual output surface' occurrences to leave consistent
  - instruction: read the five edited passages side by side; nothing in CI checks this
  - honesty: the five prose files agree with each other after the sweep, not merely each with the code
- visualize resolves to the full render path — recipe, job, artifact on disk, provenance — and the artifact is an IMAGE OR A VIDEO. Both media types are first-class from the first slice, not image-now-video-later.
  - instruction: include at least one video render in the acceptance run, not only an image
  - honesty: the video half is genuinely exercised in the first slice and not deferred, since deferring it is how image-only assumptions get baked into the recipe type
- the template graph is operator-supplied: render takes a graph path plus the declared recipe-field-to-node-input mapping. innereye ships no default graph and does not silently pick one.
  - instruction: test the no-graph path explicitly and assert the exit code and the hint text
  - honesty: omitting --graph produces an honest error naming how to get one, and never silently falls back to a bundled or downloaded default
- there is a seam that can fetch a template graph rather than requiring a local file, exercised as a DEMO path — not the default, and not a hidden fallback when --graph is omitted.
  - instruction: make the demo a named, separate invocation and assert the default path never touches the network
  - honesty: the demo download is opt-in and visibly distinct from the operator-supplied path, so nobody ships a pipeline that silently depends on raw.githubusercontent.com being reachable
- video params are ordinary recipe fields, not a special case: length and fps are explicit node inputs (wan-t2v node 40 EmptyHunyuanLatentVideo length 81, node 28 SaveAnimatedWEBP fps 16; hunyuan 1920x1056 length 49 fps 24) — the same flat node-input mapping that covers image params covers video, so one recipe compiler handles both
  - instruction: implement image and video through the same compile function or record why that failed
  - honesty: one recipe compiler really does cover both media without a media-type branch inside it, with the branch confined to output collection
- ComfyUI validates missing weights AT SUBMIT, so innereye must not reimplement it: POST /prompt with a graph naming absent weights returns a structured `prompt_outputs_failed_validation` with `node_errors` keyed by node id, giving type `value_not_in_list`, the `input_name`, the `received_value` and the full list of valid values. That is a better error than a client-side /`object_info` pre-flight could construct. innereye's job is to SURFACE that payload as CliError.remediation, not to duplicate the check. (Verified live against 127.0.0.1:8188 on 2026-09-16.) The guide's two halves still do not match — setup.sh fetches Z-Image-Turbo while the 8 api graphs need a separate 70-230GB model set — which is what makes this failure path common enough to matter
  - instruction: before submit, GET /`object_info` and check every loader node's named file is in the server's model list; the failure message must name the missing file and the tier or URL that provides it
  - honesty: a missing-weights failure is caught before submit and reports the missing filename, rather than surfacing as an opaque ComfyUI execution error after the job is queued
- the spec models jobs on the WRONG ComfyUI API: c10 assumes POST /prompt + `GET /history/<id>` polling, but the pinned v0.33.2 exposes a first-class jobs API — GET /api/jobs (filterable, sortable, paginated), `GET /api/jobs/{job_id}`, `POST /api/jobs/{job_id}/cancel`, POST /api/jobs/cancel — whose live status enum is pending, `in_progress`, completed, failed, CANCELLED (five states; the server's own 400 on an invalid filter enumerates them). /history cannot distinguish queued from running from failed; /api/jobs can. (Verified live on 127.0.0.1:8188.)
  - instruction: compile the job model against /api/jobs first; keep /history only as a fallback when the endpoint 404s. Assert all five states round-trip: pending, `in_progress`, completed, failed, cancelled
  - honesty: the /api/jobs endpoints exist and behave as documented on the running v0.33.2 server, not merely in its source
- the job lifecycle in the spec is happy-path only: submit / status / fetch has no CANCEL and no FAILED terminal state, yet the server exposes POST /interrupt, POST /api/jobs/{id}/cancel and POST /api/jobs/cancel, and JobStatus includes failed. An agent that submits a multi-minute video render and changes its mind, or whose job dies in the sampler, has no verb and no defined exit code
  - instruction: add a cancel verb wired to POST /api/jobs/{id}/cancel, and give failed its own non-zero exit carrying the server's error text; test both against the live server
  - honesty: a failed ComfyUI job surfaces to the caller as a non-zero exit with the server's error text, never as an empty successful fetch
- every render leaves TWO copies and innereye owns only one: SaveImage writes into ComfyUI's own output dir via `folder_paths`.`get_save_image_path` with an auto-incrementing counter (nodes.py:1694), so the server accumulates `prefix_00001_`.png forever while innereye copies bytes out via /view to its own predictable path. Nothing cleans the server-side copy; on a box already holding 70GB of weights that is unbounded growth nobody owns
  - instruction: document that ComfyUI retains its own copy under its output dir with an auto-increment counter; either offer an explicit cleanup or state plainly that the server-side copy is the operator's to manage
  - honesty: innereye either documents the server-side accumulation as the operator's to manage, or offers an explicit cleanup — it must not silently imply its own artifact path is the only copy
- a predictable artifact path is a DESTRUCTIVE path: the spec promises predictable paths and records the seed, so re-running the same recipe with the same seed resolves to the same filename and silently overwrites the earlier artifact and its provenance sidecar — destroying the very evidence the reproducibility claim depends on. Writes must be collision-safe or refuse to clobber without an explicit flag
  - instruction: make artifact writes collision-safe: a write that would land on an existing artifact or sidecar refuses with a non-zero exit unless an explicit overwrite flag is passed. Test by rendering the same recipe and seed twice
  - honesty: a second render that would land on an existing artifact path either refuses with a non-zero exit or writes a distinct path — it never overwrites a prior artifact or sidecar in place
- the job store has no declared home or concurrency story: c28's honesty condition demands a job submitted in one process be collectable by another, which makes the store shared mutable state — but no claim says where it lives (CWD-relative? XDG? repo-local?), what happens when two innereye processes submit at once, or how pytest -n auto avoids colliding on it. ComfyUI's own queue is a second, external store that can disagree with it after a server restart invalidates a `prompt_id`
  - instruction: declare where the job store lives and give it a schema version field from day one; test two concurrent submits and a submit-then-server-restart, and make pytest -n auto safe against it
  - honesty: two concurrent submits produce two distinct, both-collectable job records, and a job whose `prompt_id` the server no longer knows reports a distinct recoverable state rather than hanging or crashing

## Honesty conditions

- a cold run on a machine with ComfyUI running produces an artifact and a provenance sidecar, and the preview renders inline in a kitty-protocol terminal rather than printing a path and calling it a preview
- the adapter's capability declaration lists embedding-to-image as unsupported from day one, so asking for it fails honestly instead of falling through to a text prompt
- no model name, graph filename or resolution is a constant anywhere in innereye — all of it resolves from the operator-supplied graph and mapping
- any template graph or recorded ComfyUI response committed as a test fixture is checked against scripts/scan-secrets.py before it lands
- no artifact bytes pass through `emit_result`, and a wait mode emits exactly one payload on stdout with all progress on stderr
- the version bump and the TestPyPI upload it spends are accepted deliberately on the first adapter commit, not discovered at PR time
- the mapping format is agreed as part of the graph contract and is not an innereye-private invention that no other tool can produce
- both readers are actually served: the --json payload carries everything an agent needs to continue without parsing prose, and the text mode is legible to the operator without --json
- the six-verb inventory and the five stale prose sentences are still accurate at implementation time, not just at scoping time
- submit and fetch genuinely survive process exit — a job submitted in one invocation is collectable by a separate later process, not just by a long-lived one
- the recorded seed is one innereye chose and wrote into the graph, never a value read back from a backend default after the fact
- byte-identical reproduction actually holds on this hardware — non-determinism in the sampler or in cuDNN kernel selection would make this claim false and it must be tested, not assumed
- innereye never tells an operator to bind 0.0.0.0 without stating the exposure, and its own default endpoint stays loopback
- the embedded-metadata behaviour is stated wherever innereye tells an agent to share or post an artifact, and a strip option exists or its absence is deliberate
- the adapter never reads the ComfyUI output directory or models directory from the local filesystem — everything goes through HTTP, so a remote server works unchanged

## Success signals

- re-running a recorded provenance JSON reproduces a byte-identical artifact in at least 1 repeat run; the dry-run default prints the compiled recipe and resolved backend in under 1 second having spent 0 GPU seconds; and a capability mismatch exits non-zero naming an alternative backend in 100 percent of cases rather than rendering something approximate
  - instruction: run the same recipe twice on the DGX Spark and hash both artifacts before committing to this signal

## Scope / boundaries

- none of the 8 playbook graphs exposes an embedding input node — they are all CLIPTextEncode/LoadImage-fed. The embedding->image modality CLAUDE.md calls 'the reason this repo is worth existing' has NO template to cite from this guide and needs custom nodes (unCLIP / IPAdapter / raw CONDITIONING injection). This guide does not close that gap
  - instruction: write the capability-mismatch test for the embedding case before any embedding support exists
- the guide is not a model commitment: the quick-start page walks Z-Image-Turbo (`z_image_turbo_bf16` + `qwen_3_4b` + ae.safetensors, ~20GB) while the same playbook's assets/ ship flux/hidream/wan/hunyuan/cosmos graphs instead. The model and graph are configuration innereye resolves, never a constant it hardcodes
  - instruction: grep the diff for safetensors and for hardcoded dimensions before opening the PR
- scan-secrets.py permits what this needs and forbids one specific thing: its endpoint check only parses files that are valid JSON and only inspects keys matching ^(base\[`_`-\]?url|endpoint|url|host)$, allowing localhost/127.0.0.1/0.0.0.0/::1. So <http://127.0.0.1:8188> is safe anywhere, and NVIDIA/huggingface URLs are safe in .md and Python docstrings — but a committed template-graph or ComfyUI /history fixture .json carrying a non-local url/host key WILL fail CI
  - instruction: run python3 scripts/scan-secrets.py on the fixture paths as part of writing them
- `_output.py` has no binary and no streaming path: `emit_result` does a single json.dump or str() to stdout, `emit_diagnostic` is stderr-only strings. So artifact BYTES never flow through the output layer — they are written to disk by the verb and `emit_result` returns paths plus provenance. A --wait mode prints progress via `emit_diagnostic` and emits exactly one final payload
  - instruction: assert in tests that stdout parses as a single JSON document in --json mode even with --wait
- publish.yml is path-filtered to pyproject.toml and innereye/\*\* — so the very first commit that adds innereye/backends/comfyui.py triggers a REAL TestPyPI upload of `<version>.dev<run_number>` on the PR, and a real PyPI upload on merge. Version numbers are spent on both indexes, irreversibly, from the first adapter commit onward
  - instruction: bump the version in the same commit that first adds a file under innereye/
- the operator-supplied graph is a PAIR, not a file: a template graph is inert without a declared mapping from recipe fields to node input paths (prompt -> 6.inputs.text, seed -> 25.inputs.`noise_seed` differ per graph — hidream saves at node 12, flux at node 9). So --graph must be accompanied by a mapping, and the demo seam supplies both together
  - instruction: check whether the mapping shape should be raised as an issue on embeddings-cli or storybook-cli before inventing one
- ComfyUI has NO authentication: comfy/`cli_args.py` offers --tls-keyfile/--tls-certfile but no auth flag of any kind, and the playbook launch.sh runs python main.py --listen 0.0.0.0, binding every interface. On this machine that is the WiFi LAN. Anyone on the network can queue work on the GB10, read GET /history for every prompt ever run, and GET /view any output. innereye must document this and default its own guidance to --listen 127.0.0.1
  - instruction: default every documented endpoint and example to 127.0.0.1; wherever innereye tells an operator to launch ComfyUI, state that the server has no authentication and that --listen 0.0.0.0 exposes the GPU and all prior prompts to the LAN
- the artifact ALREADY carries the full recipe before innereye writes a sidecar: SaveImage injects metadata.`add_text`('prompt', json.dumps(prompt)) plus `extra_pnginfo` into the PNG (nodes.py:1700-1704), and the WebP path calls `_create_webp_metadata` and saves it as EXIF (`comfy_api`/latest/`_ui.py`). Good for provenance and a clean result for both media — but it means sharing a render SHARES THE PROMPT AND THE WHOLE GRAPH, which no claim states. An agent attaching a render to a PR leaks its prompt
  - instruction: state the embedded-metadata behaviour wherever innereye suggests sharing or posting an artifact; decide deliberately whether a strip option ships, and record the decision either way

## Non-goals

- innereye never runs the guide's setup: setup.sh creates a venv, pip-installs torch cu130, clones ComfyUI v0.33.2 and wgets ~20GB of safetensors from huggingface. That is the operator's one-time prerequisite; innereye detects a server and fails honestly when there isn't one
- do not assume CI catches an unregistered verb: tests/`test_cli_introspection.py` has no parametrization over registered commands, and the only generic gate (`test_every_catalog_path_resolves`, `test_cli.py`:111-115) walks catalog ENTRIES outward — so a render verb missing an explain entry, a --json flag or a noun overview fails NOTHING today. The agent-first rubric lives in teken cli doctor --strict, not in pytest
- harness CI does not widen for a domain verb: docs/harness-invocations.yaml and scripts/harness-smoke.py verify prompt-file presence, skills-discovery wiring and backend-fingerprint registration — never prose or CLI verbs. No new entry is needed there, and no CI job will notice if the five stale sentences are left behind

## Assumptions

- the development machine is a DGX Spark (nvidia-smi reports GB10) but has NO ComfyUI: nothing listens on 127.0.0.1:8188, no ComfyUI checkout, no `z_image_turbo` weights on disk. So the first slice must be buildable and testable with NO live server — mocked HTTP throughout — and 'backend unreachable' is the first real error path, not an edge case
- the exit-code policy has no slot for the error this feature creates most: `_errors.py` defines 0/1/2 with '3+ reserved'. 'ComfyUI unreachable' and 'capability mismatch' both have to land as 1 or 2 unless the policy is extended — and `_dispatch` wraps any non-CliError exception as `EXIT_USER_ERROR`, so a backend timeout raised as anything else would misreport as a user error
- the playbook's video output is ANIMATED WEBP, not mp4 — every video graph ends in SaveAnimatedWEBP. If 'video output' is expected to mean a real video container, that needs either a different save node (`VHS_VideoCombine`) or an ffmpeg transcode step, which the playbook Dockerfile does install. Taking the graphs as shipped means WebP is what lands on disk
- the whole frame assumes ComfyUI is LOCAL, but the guide's own launch command binds 0.0.0.0, which exists precisely so the server can be remote. If the server is on another host, the artifact is not on innereye's filesystem at all and /view is the only way to obtain bytes, ComfyUI's model list is the remote machine's not the local one, and c31's pre-submit weight validation must query the server rather than look at a directory
  - instruction: route everything through HTTP — never read ComfyUI's output or models directory from the local filesystem — so a remote server works unchanged; assert no local path to the ComfyUI install appears in the adapter

## Scope exploration

- `s1` — `NVIDIA dgx-spark-playbooks nvidia/playbook-comfyui/assets/workflow_api/ (8 *.api.json graphs)`: the quick-start's own repo already ships API-format ComfyUI graphs for text2img (flux, hidream), img2video (wan), text2video (wan, hunyuan), video2world (cosmos) and controlnet (flux) — innereye's template-graph library can cite these instead of authoring graphs
  - seeds: `c2`
- `s2` — `flux-text-to-image.api.json node graph (fetched and dumped node-by-node)`: seed, steps, sampler, width/height and prompt are all explicit node inputs in the API-format graph, so the recipe->node mapping is a flat key path and seed capture needs no ComfyUI cooperation
  - seeds: `c3`
- `s3` — `wan-image-to-video.api.json node 52 (LoadImage)`: image inputs are referenced by server-side filename, not inlined, so the adapter needs an upload step before submit — a detail that shapes the adapter interface, not just the ComfyUI implementation
  - seeds: `c4`
- `s4` — `all 8 workflow_api/*.api.json class_type listings`: no embedding/CONDITIONING input node appears anywhere in the playbook graphs — the guide covers text and image inputs only, so it cannot be the basis for the embedding->image capability
  - seeds: `c5`
- `s5` — `playbook setup.sh + launch.sh (fetched verbatim)`: setup.sh is a 20GB model download plus a ComfyUI clone; launch.sh is 'python main.py --listen 0.0.0.0'. Provisioning stays outside innereye, matching the README non-goal 'Not a hosting service'
  - seeds: `c6`
- `s6` — `local machine probe: curl 127.0.0.1:8188, find for z_image_turbo*, nvidia-smi`: GB10 DGX Spark confirmed, but ComfyUI is absent — the adapter cannot be developed against a live server today, so a mocked transport seam is a build-order requirement not a nicety
  - seeds: `c7`
- `s7` — `environment TERM=xterm-ghostty / TERM_PROGRAM=ghostty`: the operator's terminal supports the kitty graphics protocol, so inline preview is achievable natively rather than needing storybook-cli or webglass-cli for the first slice
  - seeds: `c8`
- `s8` — `build.nvidia.com quick-start page vs dgx-spark-playbooks/assets/ contents`: the guide's prose and its own assets name different models — treat the guide as one worked example of a configurable template graph, not as the canonical model choice
  - seeds: `c9`
- `s9` — `pyproject.toml deps + bandit config; .github/workflows/tests.yml lint job`: runtime deps are empty and must stay so; bandit's B310 urlopen audit is unskipped, so the HTTP client needs an explicit scheme guard to pass the lint gate
  - seeds: `c10`
- `s10` — `scripts/scan-secrets.py _ENDPOINT_KEY_RE / _ALLOWED_HOSTS + tests/test_scan_secrets.py`: the gate never fires on markdown or Python, only on parseable JSON under four key names — which is exactly the file type a vendored ComfyUI graph or a recorded /history fixture would be, so committed fixtures need checking before they land
  - seeds: `c11`
- `s11` — `innereye/cli/__init__.py:59-135 and innereye/cli/_commands/cli.py:30-43`: the registration seam and nested-noun template are already there and need no change; the binding constraint is per-level --json on every new subparser or that subcommand's parse errors silently render as text
  - seeds: `c12`
- `s12` — `innereye/cli/_output.py:17-53 and _dispatch at cli/__init__.py:101-122`: the output contract is single-shot and text/JSON only, and `_dispatch` calls args.func(args) once with no timeout, signal or cancellation plumbing — a polling wait mode owns its own SIGINT and timeout handling entirely inside the command module
  - seeds: `c13`
- `s13` — `innereye/cli/_errors.py:16-32 and _dispatch's except branch at cli/__init__.py:114-121`: codes 3+ are reserved but undefined, so distinguishing backend-unreachable from user error needs a deliberate decision, and every adapter failure must be raised as CliError or it is misclassified as exit 1
  - seeds: `c14`
- `s14` — `learn.py, explain/catalog.py, overview.py, tests/test_cli.py, CHANGELOG.md`: three code modules carry hand-maintained verb enumerations and two carry a literal 'no generation verb implemented yet' status string that a render verb makes false
  - seeds: `c15`
- `s15` — `tests/test_cli_introspection.py + tests/test_cli.py:111-115 + innereye/explain/__init__.py:23-24`: there is no test that walks the argparse tree, so verb/catalog/--json consistency is convention-enforced only — the slice should add that generic test rather than rely on review
  - seeds: `c16`
- `s16` — `README.md, CLAUDE.md, AGENTS.override.md, AGENTS.colleague.md, QWEN.md, .pi/SYSTEM.md`: five of the six root prompt/readme files carry the same 'no render verb' claim that a render verb falsifies; .pi/SYSTEM.md carries none by design, so the sweep is five files not six
  - seeds: `c17`
- `s17` — `docs/harness-invocations.yaml + scripts/harness-smoke.py --stage config`: the harness gate is orthogonal to the domain surface, which also means the prose sweep is entirely unguarded — it has to be done deliberately in the same PR
  - seeds: `c18`
- `s18` — `.github/workflows/publish.yml path filter, dev-version sed step, and both uv publish invocations`: adding any file under innereye/ makes the PR path publish for real; this is a cost of the slice's first commit, not of its last
  - seeds: `c19`
- `s19` — `workflow_api/*.api.json output nodes across all 8 graphs`: the image/video split is a real branch in the adapter: image graphs end in SaveImage (flux node 9, hidream node 12) while ALL FOUR video graphs end in SaveAnimatedWEBP (wan-i2v 28, wan-t2v 28, hunyuan 14, cosmos 9) — two different output node classes and two different /history result keys to collect
  - seeds: `c20`
- `s20` — `scripts/scan-secrets.py run directly against a probe .py holding a raw.githubusercontent.com graph URL and a probe .json`: verified clean, exit 0 — a demo-download constant pointing at the NVIDIA playbook is safe in Python source; the gate only parses JSON files and only under url/host/endpoint/baseUrl keys, which template graphs do not use
  - seeds: `c22`
- `s21` — `wan-text-to-video, hunyuan-1080p-video, cosmos-video2world api.json node inputs`: duration (length) and fps sit alongside width/height/steps/seed as plain node inputs, so 'image or video output' does not need a second compiler — only a second output-node class and a richer provenance record
  - seeds: `c23`
- `s22` — `SaveAnimatedWEBP in all four video graphs; ffmpeg in playbook assets/Dockerfile apt-get line`: the shipped video path produces .webp, so the artifact format for the video half is a decision the guide forces rather than answers
  - seeds: `c24`
- `s23` — `flux vs hidream vs wan node numbering compared side by side`: node ids are not stable across graphs, so a graph path alone cannot be compiled — the recipe-to-node mapping is part of what the operator supplies and part of what the demo seam downloads
  - seeds: `c25`
- `s24` — `playbook assets/scripts/download-models.sh tiers vs the quick-start page setup.sh`: the quick-start downloads Z-Image-Turbo weights for which NO api graph is shipped, while the shipped api graphs need a different 70-230GB model set from a separate script — following the linked guide alone does not produce a runnable graph+weights pair
  - seeds: `c31`
- `s25` — `challenge pass / adjacent-systems lens: /home/spark/comfy/ComfyUI/server.py routes 821-1072`: the pinned server offers a richer job API than the spec assumes, including a real status enum and cancel — the job model should compile to /api/jobs, falling back to /history only if the endpoint is absent
  - seeds: `c34`
- `s26` — `challenge pass / failure-mode and lifecycle lens: server.py JobStatus + /interrupt + cancel routes`: cancel and failure are first-class in the backend but absent from the spec's job model — submit/status/fetch covers only the path where nothing goes wrong
  - seeds: `c35`
- `s27` — `challenge pass / security lens: comfy/cli_args.py:63-67 vs playbook launch.sh`: the backend ships no authn/authz and the guide's own launch command binds all interfaces — the innereye-side localhost rule in scan-secrets protects the client config, not the server exposure, which is a false sense of safety worth stating
  - seeds: `c36`
- `s28` — `challenge pass / operations and lifecycle lens: nodes.py:1692-1694 + folder_paths.py:69`: artifacts persist server-side with an auto-increment counter independent of innereye's output path — a second, growing copy the spec never mentions
  - seeds: `c37`
- `s29` — `challenge pass / data-flow and privacy lens: nodes.py save_images metadata + _ui.py save_animated_webp exif`: both image and video artifacts embed the full prompt graph, so provenance is symmetric across media (clean result) but artifacts are self-disclosing when shared, which the spec does not say
  - seeds: `c38`
- `s30` — `challenge pass / reversibility and destructive-operations lens: the spec's predictable-paths + seed-provenance claims read together`: the two claims combine into silent overwrite of prior evidence; neither claim alone shows it
  - seeds: `c39`
- `s31` — `challenge pass / concurrency and distributed-state lens: c28 honesty condition vs ComfyUI prompt_queue lifetime`: surviving process exit implies shared mutable state that no claim locates or serialises, and the server-side queue is a second store that can disagree after restart
  - seeds: `c40`
- `s32` — `challenge pass / unstated-assumptions lens: c7 local-machine assumption vs playbook launch.sh --listen 0.0.0.0`: locality is assumed throughout but never claimed; the guide's own launch command is the remote-capable one, and assuming local would bake a filesystem shortcut into the adapter
  - seeds: `c41`
- `s33` — `challenge pass / migration lens: innereye has no persisted schema today`: clean pass — there is no existing on-disk format to migrate, but the job store this slice introduces becomes the first one, so its schema needs a version field from day one or the NEXT change inherits this migration problem
- `s34` — `challenge pass / observability lens: server.py /ws progress channel and /api/jobs execution_duration`: partially examined — the server exposes progress over a websocket and duration via /api/jobs, but a stdlib-only client cannot easily consume /ws, so progress reporting for a --wait mode is bounded by the no-dependency rule; not resolved here
- `s35` — `challenge pass / rollback and recovery lens`: clean pass on the render path itself — a bad render is discarded by deleting a file — but there is no rollback for the irreversible TestPyPI/PyPI upload in c19, which is the one genuinely unrecoverable action in this slice
- `s36` — `challenge pass / live probe: POST /prompt against 127.0.0.1:8188 with absent weights`: server returns `prompt_outputs_failed_validation` with per-node `node_errors` naming `input_name`, `received_value` and the valid list — client-side pre-flight is redundant; surfacing this payload is the correct design
  - seeds: `c31`
- `s37` — `challenge pass / live probe: POST /upload/image + GET /view on 127.0.0.1:8188`: upload returns {name, subfolder, type} and the name is exactly what LoadImage consumes; /view?filename=&type=input returns the bytes. c4's honesty condition h9 is now verified against a running server, not source
  - seeds: `c4`
- `s38` — `challenge pass / live probe: GET /system_stats on the GB10`: 130.7 GB unified VRAM reported, ComfyUI 0.33.2 confirmed — OOM is a far smaller risk than assumed for 14B bf16 video models, so no VRAM-guard requirement is warranted

## Decisions

- video artifacts land as .webp for the first slice, taken from SaveAnimatedWEBP unmodified, with container recorded in provenance. No ffmpeg transcode and no `VHS_VideoCombine` swap — innereye never rewrites the operator's graph.
  - instruction: assert the provenance JSON carries an explicit container field; assert innereye submits the operator's graph byte-identical apart from the mapped recipe fields
- the acceptance run is gated on real provisioning: ComfyUI v0.33.2 plus tier-1 weights (FLUX.1-dev for image, Wan 2.1 T2V 14B for video) installed at /home/spark/comfy, so both halves of c20 are tested against a live server rather than argued.
  - instruction: the slice is not done until one image render and one video render have both produced artifacts against the local server

## Open parks

- [unknown_nonblocking] embedding-to-image has no template from this guide and needs custom nodes (unCLIP / IPAdapter). Deliberately outside the first slice, but the capability mechanism must be built so it can be added without rewriting every verb
- [unknown_nonblocking] exit code for backend-unreachable: `_errors.py` reserves 3+ but defines nothing, so ComfyUI-down currently has to land as 2 (environment). Whether to spend a new code is undecided
- [unknown_nonblocking] whether --wait progress reporting is worth a websocket client, given the stdlib-only rule: polling /api/jobs gives status transitions but not per-step progress, and ComfyUI's per-step progress is websocket-only
- [out_of_scope] the interchange format for embedding inputs must be agreed with embeddings-cli and embeddings-lens via an issue, not invented here — unresolved and out of the first slice

## Resolved vagueness

- [unknown_blocking] video artifact container: every playbook graph ends in SaveAnimatedWEBP, so taking the graphs as shipped means .webp lands on disk. Whether video output means webp-as-shipped, a `VHS_VideoCombine` swap, or an ffmpeg transcode is undecided and changes what the video half of the first slice delivers — resolved: video output means animated WebP as the playbook graphs ship it. innereye records the container in the provenance JSON so nothing downstream guesses; it does not rewrite the operator's graph and does not transcode. A real video container is deferred, not denied.
- [unknown_nonblocking] the demo download seam (c22) fetches the NVIDIA flux-text-to-image graph, which needs ~70GB of tier-1 FLUX weights — so the demo does NOT work on a box provisioned by the quick-start page alone. Either the demo documents its weight prerequisite, or it targets a graph matching the 20GB quick-start set, which NVIDIA does not publish in api format — resolved: resolved by provisioning tier-1 weights: the demo seam's flux-text-to-image graph now has matching FLUX weights on this machine, so the demo works here. The prerequisite is still documented for other operators.
- [unknown_blocking] residual surprise risk after this pass: the adapter has been designed entirely against ComfyUI SOURCE, never against a running server — no endpoint in this spec has been exercised live, because the weights were still downloading when the pass ran — resolved: resolved by live exercise: ComfyUI 0.33.2 was started on 127.0.0.1:8188 (loopback, per c36) without weights, and every endpoint the spec names was called for real — /`system_stats`, /api/jobs, /api/jobs status validation, /history, /queue, /`object_info`, /upload/image, /view, and /prompt on both an outputless and a missing-weights graph. Two confirmed claims were corrected by the results (c31, c34). Rendering itself remains unexercised pending the weights, which c33 already gates.
