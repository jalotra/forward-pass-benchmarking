# Plan 001 — Modular MAX vs SGLang+NVIDIA: small-model inference benchmark

| | |
|---|---|
| **Created** | 2026-09-17 23:30 IST |
| **Status** | Approved-in-progress |
| **Source spec** | `AGENT.md` |
| **Owner** | Shivam |

## 1. Objective

Measure how a small LLM's serving performance differs between:

- **Stack A (treatment):** **Open-source MAX APIs** — `max serve` from the
  public nightly package (`max[serve]`) or the official
  `docker.modular.com/modular/max-nvidia-full` image. **No Modular platform
  account needed.** Serving internals (Mojo kernels + Python orchestration)
  vendored from `github.com/modular/modular` → `third_party/modular` for
  reference/customization.
- **Stack B (baseline):** **NVIDIA + Triton + SGLang** — `sglang.launch_server`
  on an NVIDIA GPU (CUDA + Triton kernels — SGLang's native stack).

**Apples-to-apples:** we manage the infra for *both* stacks ourselves on
Modal — no hosted/managed serving platforms on either side. Same model, same
GPU type, same Modal region, same workload; the only variable is the engine.

Metrics (normalizing AGENT.md's "TFFT/TFFB" to standard names):

| Metric | Meaning | Source |
|---|---|---|
| **TTFT** | Time to first token (prefill latency) | Server Prometheus histograms + streaming probe |
| **TPOT / ITL** | Time per output token / inter-token latency | Server Prometheus histograms |
| **E2E latency** | Full request latency, p50/p90/p99 | k6 client-side + server histograms |
| **Throughput** | Output tokens/sec vs concurrency | k6 (token usage) + server metrics |
| **Error rate / RPS** | Under load | k6 |

## 2. Key decisions (with rationale)

| Decision | Choice | Why |
|---|---|---|
| **Model** | **`Qwen/Qwen3-4B-Instruct-2507`** (locked, single model for v1). Future additions: `Qwen3-1.7B`, `Llama-3.2-3B-Instruct` | ~4B params ≈ 8 GB bf16 ≈ 33% of L4 VRAM — comfortably "small", fully in VRAM. Dense `Qwen3ForCausalLM` — verified in MAX's registered `qwen3` arch AND SGLang's registry. **Ungated Apache-2.0** → no `HF_TOKEN` needed (Llama-3.2-3B is gated; keep as later addition). |
| **GPU** | **`L4` (24 GB)** on Modal | Minimum GPU that (a) holds full bf16 weights + KV cache and (b) is on MAX's **officially supported** list (A10/A100/L4/L40/H100+). T4 is Turing/sm_75 — NOT officially supported by MAX, and SGLang perf on it is unrepresentative anyway. A10 (24 GB) is the documented fallback. Cheapest officially-supported option (~$0.80/hr). |
| **Region** | `compute_region="us"`, `routing_region` pinned (e.g. `us-west`) | Both stacks through the same Modal proxy path → apples-to-apples client latency. |
| **MAX source** | **OSS only**: `max[serve]` nightly wheel (`whl.modular.com/nightly/simple/`) or official image `docker.modular.com/modular/max-nvidia-full`; source vendored to `third_party/modular` | User has no Modular platform account — everything used is public/open-source. Vendored source lets us read/modify serving internals (`max/python/max/serve/`). |
| **IaC** | Terraform via **`terraform_data` + modal CLI** | No official Modal TF provider; community `deevus/modal` is **uninstallable** (release artifacts 404 — verified 2026-09-17). `terraform_data` + local-exec `modal` CLI covers volumes/secrets/deploys and keeps `terraform apply/destroy` as the single entrypoint. |
| **Load gen** | **k6**, scripts authored in **TypeScript**, run locally | k6 can't run TS natively → bundle with esbuild to a single JS file per scenario, then `k6 run`. |
| **Python config** | `config.yaml` everywhere, **no argparse** | Per AGENT.md. Modal apps read `config.yaml`; TF reads `terraform.tfvars`; k6 gets env vars rendered from a YAML config by a tiny node script. |
| **Measurement layers** | (1) k6 client view through Modal proxy; (2) server-side Prometheus histograms (SGLang `--enable-metrics` on `/metrics`; MAX metrics port 8001); (3) optional in-container `max benchmark` / `sglang.bench_serving` over localhost | k6 alone can't time SSE chunks reliably → TTFT/TPOT come from engine-side histograms; k6 owns E2E latency, RPS, error rate, and throughput-under-load. Layer 3 removes proxy+internet RTT for a pure-engine number. |

## 3. Target repo layout

```
inference-engineering/
├── AGENT.md                     # spec + progress tracker
├── plans/
│   └── 001-max-vs-sglang-benchmark.md
├── Makefile                     # deploy/stop/urls/check targets
├── requirements.txt             # local deploy-time tooling (modal, pyyaml)
├── .venv/                       # local modal+pyyaml env for deploys
├── infra/
│   └── terraform/               # terraform_data + modal CLI (no provider — see IaC row)
│       ├── main.tf  variables.tf  outputs.tf  terraform.tfvars.example
├── src/
│   ├── config.yaml              # SINGLE SOURCE OF TRUTH: model, gpu, regions, ports, volumes
│   ├── bench/                   # shared package (baked into both images)
│   │   ├── settings.py          #   config.yaml -> typed dataclasses (deploy-time only)
│   │   ├── images.py            #   sglang_image() / max_image() builders
│   │   ├── volumes.py           #   named Modal volumes (hf/max/results caches)
│   │   ├── readiness.py         #   wait_for_health / warmup / weight prewarm (stdlib only)
│   │   └── telemetry.py         #   `python -m bench.telemetry` /metrics scraper -> results vol
│   └── apps/
│       ├── sglang_server.py     #   Modal app "bench-sglang" (@app.server, L4, vanilla sglang)
│       └── max_server.py        #   Modal app "bench-max" (@app.server, L4, max serve)
├── k6/
│   ├── package.json  tsconfig.json  esbuild.config.mjs
│   ├── config.yaml              # scenarios, endpoints, request shape
│   ├── run.mjs                  # config.yaml -> k6 -e flags -> `k6 run`
│   └── src/  smoke.ts  latency.ts  sweep.ts  lib/client.ts
├── third_party/
│   └── modular/                 # vendored OSS MAX source (sparse: max/ + examples/, ~250 MB)
│       └── max/python/max/serve/    # serving internals: api_server, router, scheduler, pipelines
├── results/                     # <run-id>/k6-summary.json + metrics scrape + engine bench JSON
└── reports/                     # final comparison write-up
```

## 4. Ordered phases

### Phase 0 — Access & guardrails
1. `modal token new` / confirm Modal CLI auth; confirm `terraform`, `k6`, `node`, `esbuild` locally.
2. If using Llama: create Modal secret `hf-token` (also via TF provider).
3. **Set Modal workspace spend limit to $50** (`Settings → Usage`) — hard stop, non-negotiable.
4. Scaffold repo layout above; `.gitignore` for `results/`, `dist/`, `.terraform/`.

**Gate:** `modal token` works; spend limit visible in dashboard.

### Phase 1 — Model/GPU validation (cheap, CPU-only or local)
1. ✅ Arch support verified in vendored source: `qwen3` arch registers `Qwen3ForCausalLM` (covers `Qwen3-4B-Instruct-2507`); SGLang registry also covers it. Re-confirm at runtime with `max list` inside the Phase-3 image.
2. Pin model HF revision SHA; record VRAM math (weights ~8 GB + KV @ chosen `max-length` on 24 GB L4) in this doc.
3. Lock `modal_apps/config.yaml`: model `Qwen/Qwen3-4B-Instruct-2507`, revision, `gpu: "L4"`, `max_length`, region, port 8000.

**Gate:** `Qwen3ForCausalLM` in `max list`; weights ≈ 33% of 24 GB VRAM.

### Phase 2 — SGLang baseline on Modal
1. `modal_apps/sglang_server.py`: `lmsysorg/sglang:<pinned-tag>` image; `HF_HOME` on a Modal Volume (`huggingface-cache`) so weights download once; `--enable-metrics`; `@app.server` with `gpu="L4"`, `min_containers=0`, `target_concurrency` set per workload, `startup_timeout` generous.
2. Keep it **vanilla** — no speculative decoding, no exotic flags; parity with MAX defaults is the point.
3. `modal deploy`; smoke test `/v1/chat/completions`; confirm `/metrics` reachable through the endpoint URL.

**Gate:** coherent response + Prometheus metrics exposed.

### Phase 3 — MAX server on Modal (OSS APIs) ⚠️ highest technical risk
1. **Source vendored** ✅ — `third_party/modular` (sparse checkout: `max/` + `examples/`).
   Key serving internals for reference:
   - `max/python/max/serve/api_server.py` — server entrypoint (`max serve` launches this)
   - `max/python/max/serve/router/openai_routes.py` — OpenAI-compatible routes, SSE streaming
   - `max/python/max/serve/pipelines/llm.py` — `TokenGeneratorPipeline` (prefill/decode queues)
   - `max/python/max/serve/scheduler/` — batch construction, prefill/decode schedulers
   - `max/kernels/` — Mojo GPU kernels; `max/python/max/{nn,pipelines,kv_cache,driver}` — model archs + runtime
2. Image — pick whichever proves more reliable:
   - **(preferred)** `modal.Image.from_registry("docker.modular.com/modular/max-nvidia-full:<pinned-tag>")` — official Modular NVIDIA image, `max serve` included.
   - **(fallback)** `uv_pip_install("max[serve]", extra_index_url="https://whl.modular.com/nightly/simple/", extra_options="--prerelease=allow")` in a debian_slim image.
   - **(last resort)** build from vendored source (Bazel — heavy; avoid unless needed).
3. `max_server.py`: subprocess `max serve --model <hf-id>` (defaults: GPU auto-detect, binds :8000); `max warm-cache` during image build or first run to pre-bake weights+MEF compile into a Volume.
4. Readiness loop on `/v1/health` (compiles can take ~10 min first time — heartbeat logs, not a hang).
5. Expose metrics port (8001) — if `@app.server` fronts a single port, scrape via `modal.forward`/tunnel or have the container dump metrics to the results Volume on a timer.
6. Smoke test identical to Phase 2.

**Gate:** `max serve` answers on L4 with coherent output. *If L4 fails → try A10; if MAX-on-Modal is blocked entirely, escalate to user before burning budget.*

### Phase 4 — Terraform layer ✅ scaffolded (validates clean)
1. No usable provider (deevus/modal artifacts 404) → `terraform_data` + modal CLI:
   - `terraform_data.volumes` — `modal volume create` for the three cache/result volumes
   - `terraform_data.hf_secret` — `modal secret create hf-token` (only when `var.hf_token` set)
   - `terraform_data.deploy_{sglang,max}` — `modal deploy src/apps/*.py`, retriggered by a `src/` content hash; destroy provisioner runs `modal app stop`
2. `terraform init && validate` passes; `apply` gated on Modal auth token.
3. `terraform destroy` → `modal app stop` both apps (volumes kept deliberately).

**Gate:** `terraform apply` stands up both apps end-to-end.

### Phase 5 — k6/TS load harness (local) ✅ scaffolded (bundles + inspect pass)
1. `esbuild` bundles each scenario TS → `dist/*.js` (esm, k6/* external); `tsc` clean; `k6 inspect` accepts all three.
2. Scenarios (config via `k6/config.yaml` rendered to `-e` flags by `run.mjs`):
   - `smoke`: 1 VU × few iters — correctness.
   - `latency`: `--max-concurrency 1`-equivalent, fixed prompt shape — best-case TTFT/E2E.
   - `sweep`: ramping VUs 1→2→4→8→16→32 — throughput knee + latency degradation.
   - `rate` (optional): constant arrival-rate executor.
3. Custom k6 metrics: `ttft_ms` (via `stream` response or paired with server histograms), `e2e_ms`, `output_tokens/sec` parsed from `usage`, `http_req_failed` rate.
4. Each run writes `results/<run-id>/summary.json` (`--summary-export`).

**Gate:** smoke run against both endpoints produces sane numbers.

### Phase 6 — Benchmark runs & collection
1. Run order per stack: smoke → latency → sweep. **Sequential stacks** (one GPU app live at a time) to halve spend.
2. During each run, scrape `/metrics` (SGLang) / metrics port (MAX) at fixed cadence → `results/<run-id>/prom-*.json`.
3. Optional layer-3: `max benchmark` / `sglang.bench_serving` inside each container over localhost for proxy-free numbers.
4. Label every result dir: `<date>_<stack>_<scenario>`.

**Gate:** complete result set for both stacks, same scenarios.

### Phase 7 — Analysis & report
1. Normalize metrics into one table: TTFT/TPOT/E2E p50/p90/p99 × concurrency × stack; throughput-vs-concurrency curves.
2. `reports/001-max-vs-sglang.md`: setup, configs, numbers, verdict on where MAX wins/loses for small models.
3. Update `AGENT.md` progress section.

### Phase 8 — Teardown & cost audit
1. `modal app stop` both apps (`terraform destroy` where applicable); keep HF-cache Volume only if a re-run is likely (storage is cheap, GPU idle is not).
2. Pull Modal usage/billing report; record total spend in the report. **Must be < $50.**

## 5. Budget model

| Item | Estimate |
|---|---|
| L4 GPU | ~$0.80/hr |
| Dev/debug (Phases 2–4) | ~2–4 GPU-hr |
| Bench runs ×2 stacks | ~2–4 GPU-hr |
| Volume storage (small model) | < $1 |
| **Expected total** | **~$5–10, hard cap $50 via spend limit** |

Cost controls: `min_containers=0`, sequential stacks, `startup_timeout`/function timeouts, HF+MEF caches in Volumes (weight re-download = billed wall time), stop apps immediately after runs.

## 6. Risks & open questions

| Risk / open question | Mitigation |
|---|---|
| ~~"Triton" ambiguity~~ **Resolved 2026-09-17:** Stack B = SGLang's native CUDA+Triton kernel stack (standard SGLang deployment, not Triton Inference Server) | — |
| MAX won't run on L4 / driver ≥580 requirement fails on Modal | Phase 3 smoke test is first spend; fallback A10 → L40S; escalate if all fail |
| ~~No official TF provider~~ **Resolved:** `deevus/modal` uninstallable (artifacts 404); using `terraform_data` + modal CLI instead | — |
| k6 can't time SSE chunks → TTFT weak client-side | Server Prometheus histograms are primary TTFT/TPOT source; optional localhost bench layer |
| Modal proxy RTT inflates client latency | Same path for both stacks (fair comparison) + layer-3 localhost numbers |
| MAX metrics port (8001) not fronted by `@app.server` | Tunnel/`modal.forward`, or in-container scrape → results Volume |
| Gated Llama needs HF approval | Prefer ungated Qwen3-4B; HF token via TF-managed secret if Llama chosen |

## 7. Progress log

| Date (IST) | Phase | Note |
|---|---|---|
| 2026-09-17 23:30 | 0 | Plan created; workspace contains only `AGENT.md`, `plans/`, `skills/` (modal + modular skill refs available locally) |
| 2026-09-17 23:36 | — | Scope clarified: **OSS MAX APIs only** (no platform account); infra self-managed on both sides. Vendored `modular/modular` source → `third_party/modular` (sparse `max/`+`examples/`, ~250 MB). Found official image `docker.modular.com/modular/max-nvidia-full`. |
| 2026-09-17 ~23:40 | 1 | **Model locked: `Qwen/Qwen3-4B-Instruct-2507`** (rev `cdbee75f`) — verified `Qwen3ForCausalLM` in vendored MAX `qwen3` arch + SGLang support; ungated → no HF token needed. "Triton" resolved: SGLang native CUDA+Triton stack. |
| 2026-09-17 ~23:50 | 0–5 | **Full scaffold built & locally verified.** `src/` (config.yaml + bench pkg + both Modal apps) imports clean; k6/TS harness bundles + passes `k6 inspect`; terraform `init`+`validate` clean (switched to terraform_data+CLI after deevus/modal proved uninstallable). `.venv` created, k6 2.2.0 via brew. **Blocker: `modal token new` needed before deploys.** |
| 2026-09-18 ~00:15 | 2–3 | **BOTH STACKS DEPLOYED & SMOKE-VERIFIED.** `bench-sglang` + `bench-max` serving coherent `Qwen3-4B` answers on L4. Fixes along the way: `add_local_*` ordering (copy=True on both); `docker.modular.com` anonymous pull rate-limit → MAX now installs `max[serve]` wheel from `whl.modular.com` nightly index onto `nvidia/cuda:13.0.1-devel` (add_python 3.12). Telemetry verified: `sglang.prom` + `max.prom` land in `bench-results` vol every 5s — MAX exposes `maxserve_time_to_first_token_milliseconds` on :8001, SGLang exposes `sglang:*` histograms on :8000. k6 smoke = 0/5 failed vs SGLang. Note: containers scale to zero quickly on idle → warm-up needed per session. Endpoints: sglang `https://jalotratrading--bench-sglang-sglang.us-west.modal.direct`, max `https://jalotratrading--bench-max-max.us-west.modal.direct` |
| 2026-09-18 ~01:45 | 6 | **FIRST 10-MIN RUNS + METRICS PIPELINE DONE.** Discovered Modal kills idle/scaled containers ~60-90s — runs start mid-boot → 503 flood first ~5min; each run still yields ~5min clean **200-window** (window where responses are HTTP 200, per user slicing convention). `target_concurrency=256` keeps container alive under load. Pipeline: `scripts/collect_metrics.sh` → `metrics/<model>/<HH-MM>/` (prom snapshots, k6 ndjson+summaries, server logs, manifest); `scripts/analyze_metrics.py` → detects 200-windows, aligns both stacks to same VU stages, normalizes units (sglang s→ms), seaborn plots + summary tables. **First numbers (VU4-32 window):** TTFT max ~100ms vs sglang ~1.8s (queue-inclusive); ITL/token sglang ~40ms vs max ~46ms; E2E p50 sglang 8.6s vs max 10.2s but sglang tail worse (p99 19.3 vs 14.1s); throughput both ramp to ~600-800 tok/s at VU32. |
