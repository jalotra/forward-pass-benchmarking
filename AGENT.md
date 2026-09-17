Objective : 
I know that Modular has launched Max (which is a inference platform); this is what I want to measure : 
1. How does small models performance varies (things like TFFT, TFFB ...) vs a native SGLang + Nvidia Stack 

Tech Stack : 
1. I would be using k6/http to send out load-test over http 
2. Would be rent out compute from modal (and this would be within a budget of $50 in total)
3. Setting up infra on modal should / would be done via terraform (and we should be choosing the minimum GPU which would be able to support whole model weights in VRAM fully)
4. Note on Python Side : 
a) Dont use argparse, please use config.yaml files to pass in values to programs in
b) on terraform side (please use official / unofficial) modules to setup the infa 
c) run k6/http locally (and write these scripts in ts)

---

## Tracking

Plans live in `plans/` as `NNN-<slug>.md` (numbered, timestamped at top of each file).
Update this table + the plan's progress log as work advances.

| Plan | Goal | Status | Last updated |
|---|---|---|---|
| [plans/001-max-vs-sglang-benchmark.md](plans/001-max-vs-sglang-benchmark.md) | OSS MAX APIs vs SGLang+NVIDIA (CUDA+Triton) small-model benchmark — self-managed on Modal + k6/TS + Terraform | **First 10-min runs + metrics pipeline done** — `metrics/` has prom/k6/logs + seaborn plots; TTFT max~100ms vs sglang~1.8s, ITL sglang~40 vs max~46ms | 2026-09-18 01:45 IST |

