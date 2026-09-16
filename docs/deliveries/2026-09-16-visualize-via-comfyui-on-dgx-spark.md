# Delivery Summary — visualize via ComfyUI on DGX Spark

plan: `visualize-via-comfyui-on-dgx-spark` · run: `complete` · date: `2026-09-16`
baseline: `devague summary skeleton`

## Intent

Ship innereye's first generation feature: turn a prompt into an actual image or
video on a DGX Spark by compiling a portable recipe into an operator-supplied
ComfyUI template graph, submitting it as a job, and writing the artifact to disk
with provenance beside it. The run executed the 14-task plan seeded from the
converged, challenged frame of the same slug. It was built serially by the main
agent rather than fanned out to a workforce, at the user's direction.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — recipe type and the operator-supplied graph+mapping contract
- `t2` — stdlib-only HTTP transport with a scheme guard
- `t3` — capability declaration and honest-refusal negotiation
- `t4` — versioned, concurrency-safe job store that survives process exit
- `t5` — provenance sidecar and collision-safe artifact paths
- `t6` — terminal preview with kitty protocol and an honest fallback
- `t7` — ComfyUI adapter: compile, submit, poll, cancel, collect
- `t8` — render verb, dry-run by default, with the demo graph seam
- `t9` — job noun group: submit, status, fetch, cancel, overview
- `t10` — fixtures and the committed-JSON secrets gate
- `t11` — register the verbs and sweep the in-repo enumerations in lockstep
- `t12` — sweep the five prose surfaces and state the ComfyUI exposure
- `t13` — version bump, changelog, and the deliberate index spend
- `t14` — live acceptance: one image and one video against the running server

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `innereye/recipe.py` — `Recipe`, `GraphMapping`, `compile_recipe`, graph/mapping loaders. One compile path covers image and video; unmapped fields are refused, not dropped. |
| `t2` | delivered | `innereye/backends/_http.py` — GET/POST-JSON/multipart/bytes over `urllib` behind an explicit scheme guard. `dependencies = []` unchanged; bandit reports no issues with one narrow B310 suppression. |
| `t3` | delivered | `innereye/backends/__init__.py` — `Capability`, the `Backend` protocol, `negotiate()`. `embedding_to_image` declared unsupported and refused. |
| `t4` | delivered | `innereye/jobs.py` — one file per job, atomic `os.replace`, `schema_version = 1`, fails closed on a newer schema, `STATE_UNKNOWN` for a job the backend forgot. |
| `t5` | delivered | `innereye/provenance.py` — sidecar with backend/seed/container/resolution/steps/recipe; `choose_seed` + `assert_seed_submitted`; collision-safe writes checking both paths before either. |
| `t6` | delivered | `innereye/preview.py` — kitty graphics, a stdlib PNG decoder (zlib + unfilter) driving an ASCII fallback, and a described path for undecodable media. |
| `t7` | delivered | `innereye/backends/comfyui.py` — compile/upload/submit/status/fetch/cancel against `/api/jobs` with a `/history` fallback; surfaces the server's `node_errors`. |
| `t8` | delivered | `innereye/cli/_commands/render.py` — dry-run by default, `--apply`, `--wait`, `--preview`, and the separately named `--demo` download mode. |
| `t9` | partial (by design) | `innereye/cli/_commands/job.py` — `overview`, `status`, `fetch`, `cancel`. **No `submit` sub-verb**; see Drift `t9`. |
| `t10` | delivered | All ComfyUI transport mocked in tests; no test needs a live server or a fixed port. `scan-secrets.py` clean over 109 files. |
| `t11` | delivered | Verbs registered; `learn.py` `_TEXT` + `_as_json_payload`, `overview.py` `_VERBS`, `explain/catalog.py` `_ROOT` + new entries all swept in one commit. New generic argparse-tree tests added. |
| `t12` | delivered | `README.md`, `CLAUDE.md`, `AGENTS.override.md`, `AGENTS.colleague.md`, `QWEN.md` no longer claim the domain is unimplemented; each states the ComfyUI no-authentication exposure. `.pi/SYSTEM.md` untouched, as planned. |
| `t13` | delivered | `0.10.1` → `0.11.0` via the `version-bump` skill, with a full Keep-a-Changelog entry, in the same commit as the first `innereye/` code. |
| `t14` | delivered | FLUX.1-dev: 1024×1024 PNG in ~47 s. Wan 2.1 T2V: 17-frame animated WebP. Same-seed re-run byte-identical. Dry run 0.05 s, zero submissions. |

## Mid-work Decisions

Three deviations were recorded via `/deviate` at the moment each occurred, and
**all three were subsequently approved by the user**. They are the recorded
ground truth for the Drift section below, consumed here rather than
re-litigated:

- `d1` (approved) — the `job` noun group ships no `submit` sub-verb. Reason: a
  `job submit` would need the entire render surface (`--graph`, `--mapping`,
  `--prompt`, every param) to construct a recipe, duplicating `render` exactly.
  `render --apply` *is* the submit step and already returns a job handle.
- `d2` (approved) — `GraphMapping` accepts a **list** of node paths per recipe
  field. Reason: `flux-text-to-image` reads the resolution in two nodes
  (`EmptySD3LatentImage` 27 and `ModelSamplingFlux` 30); mapping `width` to only
  one silently mis-shifts the sampler while appearing to work.
- `d3` (approved) — `t14` ran **before** `t12`/`t13`, inverting the plan's wave
  order. Reason: the user's stated goal was to actually generate an image; the
  dependency was PR-hygiene ordering, not a functional prerequisite.

Decisions not covered by any deviation record:

- Graph/mapping **loaders** live in `recipe.py` rather than a new module, keeping
  them inside `t1`'s "operator supplies a pair" contract instead of creating a
  file no task owned.
- The build was executed **serially by the main agent**, not fanned out via
  `/assign-to-workforce`. Wave 0 was six-wide and file-disjoint, but the plan's
  critical path is mostly serial after wave 1.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t9` (`d1`) | Ships `overview`/`status`/`fetch`/`cancel` but no `submit` sub-verb; `render --apply` is the submit step. Two verbs constructing the same recipe would duplicate the whole render surface. | acceptable |
| `t1` (`d2`) | `GraphMapping` gained one-field-to-many-paths, which the task's acceptance criteria did not anticipate. Required for a correct flux mapping. | acceptable |
| `t14` (`d3`) | Ran ahead of `t12`/`t13`, inverting declared wave order. `t12` and `t13` still completed before this summary. | acceptable |
| `c31` (claim, amended mid-run) | The claim originally required a client-side `/object_info` pre-flight of a graph's weights. The live probe showed ComfyUI already fails closed at submit with a richer `node_errors` payload, so the claim was amended and the pre-flight removed. | acceptable |
| `c34` (claim, amended mid-run) | The status enum was recorded as four states from a source grep; the running server enumerated **five** (`cancelled` included). Amended against the live server. | acceptable |

## Evidence

- tests: full suite `uv run pytest -n auto --cov=innereye` — **211 passed, 1
  skipped**, coverage **88.09 %** (threshold 60 %)
- tests: `tests/test_provenance.py::test_same_seed_twice_refuses_to_destroy_the_first_result` — pass
- tests: `tests/test_comfyui.py::test_all_five_states_round_trip` — pass (5 params)
- tests: `tests/test_comfyui.py::test_animated_flag_is_not_mistaken_for_media` — pass
- tests: `tests/test_job_cli.py::test_preview_is_reported_on_stderr_not_mixed_into_stdout` — pass
- tests: `tests/test_jobs.py::test_a_separate_process_can_collect_what_this_one_submitted` — pass
- tests: `tests/test_capability.py::test_embedding_input_is_refused_never_downgraded` — pass
- lint: `black --check` / `isort --check-only` / `flake8` — clean
- lint: `bandit -c pyproject.toml -r innereye` — **no issues identified**, 1 narrow `nosec B310`
- lint: `python3 scripts/scan-secrets.py` — clean, 109 files
- lint: `markdownlint-cli2` (committed files) — 0 errors
- rubric: `teken cli doctor . --strict` — **26 PASS, 0 FAIL**
- harness: `scripts/harness-smoke.py --stage config --require config` — 6 passed, 0 failed
- artifacts: `/home/spark/comfy/renders/159463c8737e_flux_output_00001_.png` (1 315 167 B, 1024×1024)
  and `/home/spark/comfy/renders/864e333bea05_wan_t2v_output_00001_.webp` (137 488 B, 17 ANMF frames)
- reproduction: both runs of seed `20260916` hashed `ed356ab1c787a04fc47896d0445bb10352c79214e5789d209b309c7a23876f4d`
- commits: `a909f9e..5356904`
- devague: obligations `o1`–`o13`, evidence `e1`–`e10` (all `proposed`), deltas `b1`–`b6` (all `proposed`)
- devague: deviations `d1`, `d2`, `d3` — **approved**

Lapse ledger evidence:

| Lapse | Code | What | Status |
|-------|------|------|--------|
| `l1` | `assumption-for-measurement` | The adapter surface was designed by reading ComfyUI's source, not by calling a running server — `c4`'s honesty condition had explicitly asked for a live check first. | approved |

`l1` was approved while true, and the live acceptance run subsequently closed it:
every endpoint the spec names was exercised against ComfyUI 0.33.2 on
`127.0.0.1:8188`. It is retained here because it correctly describes the state of
the work at the time it was filed, and because it predicted the class of bug the
live run then found.

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| `innereye render` produces a real image on a DGX Spark | high | artifact `159463c8737e_flux_output_00001_.png` · commit `5356904` |
| `innereye render` produces a real video (animated WebP) | high | artifact `864e333bea05_wan_t2v_output_00001_.webp`, 17 ANMF frames |
| Same seed reproduces a byte-identical artifact on GB10 | high | two live runs, sha256 `ed356ab1…` identical |
| Artifact writes refuse to clobber prior results and their provenance | high | test `tests/test_provenance.py::test_same_seed_twice_refuses_to_destroy_the_first_result` |
| All five ComfyUI job states round-trip through the adapter | high | test `tests/test_comfyui.py::test_all_five_states_round_trip` · live `GET /api/jobs?status=bogus` |
| Missing weights surface the server's own `node_errors`, with no client pre-flight | high | live `POST /prompt` probe · test `test_missing_weights_surfaces_the_servers_own_node_errors` |
| Job state survives process exit | high | test `tests/test_jobs.py::test_a_separate_process_can_collect_what_this_one_submitted` |
| An embedding recipe is refused, never approximated | high | test `test_embedding_input_is_refused_never_downgraded` · live CLI exit 1 |
| `--json` emits exactly one payload on stdout, even with `--preview` | high | test `test_preview_is_reported_on_stderr_not_mixed_into_stdout` |
| The runtime package has no third-party dependencies | high | `pyproject.toml` `dependencies = []` · bandit/flake8 clean |
| Dry-run is the default and spends nothing | high | measured 0.05 s · test `test_dry_run_is_the_default_and_submits_nothing` |
| `innereye job cancel` stops a live queued or running job | unverified | obligation `o13` — only exercised against a mocked transport, never against a real in-flight job |
| The adapter works unchanged against a **remote** ComfyUI | unverified | obligation `o12` — argued from "no filesystem reads", never run cross-host |
| The PR path publishes to TestPyPI and merge publishes to PyPI | unverified | obligation `o11` — no PR opened yet this run |
| The ASCII fallback renders correctly on a genuinely non-kitty terminal | unverified | exercised only with a mocked `env` dict |
| A server restart reconciles to `STATE_UNKNOWN` | unverified | tested against a mocked 404, not a real ComfyUI restart |

## Remaining Work / Follow-up

- **Adjudicate obligations/evidence `o1`–`o13`, `e1`–`e10`, deltas `b1`–`b6`** —
  all `llm`-origin and therefore `proposed`. Owner: the user. (Deviations `d1`,
  `d2`, `d3` were approved, which unblocked deltas `b4`–`b6`; those three had
  been refused by the CLI while their deviations were still proposed.)
- **`o13` — live cancel.** Exercise `innereye job cancel` against a genuinely
  in-flight job (a long Wan render is the natural candidate).
- **`o12` — remote backend.** Run the adapter against a ComfyUI on another host
  to convert `c41` from an argument into evidence.
- **`o11` — publish path.** Opening the PR will spend `0.11.0.dev<run>` on
  TestPyPI irreversibly; that is deliberate and was accepted at commit time.
- **Second adapter.** `c9`/the pluggability claim is still backed by exactly one
  plugin. The capability mechanism exists and is tested, but "pluggable" is not
  yet demonstrated.
- **Embedding inputs.** Declared unsupported and refused, which is the correct
  interim behaviour, but the interchange format still needs agreeing with
  `embeddings-cli` / `embeddings-lens` via an issue rather than invented here
  (frame park `v4`, plan risk `r1`).
- **Exit code for backend-unreachable.** `_errors.py` reserves `3+` but defines
  nothing; "ComfyUI down" currently lands as `2` (plan risk `r2`).
- **Per-step progress for `--wait`.** ComfyUI exposes it only over a websocket,
  which the stdlib-only rule makes expensive; polling gives state transitions
  but not progress (plan risk `r3`, frame park `v6`).
