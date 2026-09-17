#!/usr/bin/env bash
# Collect all benchmark artifacts into metrics/<model_short>/<HH-MM>/ for
# offline analytics (Substack write-up). Re-runnable; each collection lands in
# a fresh timestamped dir.
#
# Env overrides:
#   MODEL_SHORT  dir name for the model (default: last path segment of config's model)
#   OUT_ROOT     metrics root (default: metrics/)
#   SGLANG_RUN_START/END, MAX_RUN_START/END   ISO timestamps of the run windows
set -euo pipefail
cd "$(dirname "$0")/.."

MODAL=.venv/bin/modal
MODEL_SHORT="${MODEL_SHORT:-$(.venv/bin/python -c "
import yaml; print(yaml.safe_load(open('src/config.yaml'))['model']['name'].split('/')[-1])")}"
STAMP="$(date +%H-%M)"
OUT="${OUT_ROOT:-metrics}/${MODEL_SHORT}/${STAMP}"
mkdir -p "$OUT/k6" "$OUT/logs"

echo "==> collecting into $OUT"

# In-container Prometheus snapshots (timestamped; covers the whole run window).
echo "-- prom snapshots from bench-results volume"
$MODAL volume get bench-results sglang.prom - > "$OUT/sglang.prom" 2>/dev/null || true
$MODAL volume get bench-results max.prom   - > "$OUT/max.prom"   2>/dev/null || true

# k6 summary exports + raw per-request points (for 200-window slicing).
echo "-- k6 summaries + ndjson"
cp k6/results/*.json "$OUT/k6/" 2>/dev/null || true
cp /tmp/run3.ndjson "$OUT/k6/sglang-run.ndjson" 2>/dev/null || true
cp /tmp/max-run.ndjson "$OUT/k6/max-run.ndjson" 2>/dev/null || true

# Server-side engine logs (decode throughput, batching, errors) for the window.
echo "-- app logs"
$MODAL app logs bench-sglang > "$OUT/logs/sglang-server.log" 2>&1 || true
$MODAL app logs bench-max    > "$OUT/logs/max-server.log"    2>&1 || true

# Machine-readable context for analytics.
.venv/bin/python - "$OUT" <<'PY'
import json, sys, yaml, datetime, os
out = sys.argv[1]
cfg = yaml.safe_load(open("src/config.yaml"))
manifest = {
    "collected_at": datetime.datetime.now().astimezone().isoformat(),
    "model": cfg["model"],
    "hardware": cfg["hardware"],
    "server": cfg["server"],
    "endpoints": {
        "sglang": "https://jalotratrading--bench-sglang-sglang.us-west.modal.direct",
        "max": "https://jalotratrading--bench-max-max.us-west.modal.direct",
    },
    "run_windows": {
        "sglang": {"start": os.environ.get("SGLANG_RUN_START"), "end": os.environ.get("SGLANG_RUN_END")},
        "max": {"start": os.environ.get("MAX_RUN_START"), "end": os.environ.get("MAX_RUN_END")},
    },
    "scenario": "bench10m — ramping-vus [1,2,4,8,16,32] x 100s = 600s",
    "request_shape": {"max_tokens": 256, "temperature": 0.0, "endpoint": "/v1/chat/completions"},
    "units_note": "sglang *_seconds metrics -> ms on analysis (x1000); maxserve_*_milliseconds already ms; k6 values ms. All plots/tables in ms.",
    "files": {
        "sglang.prom": "timestamped /metrics snapshots (TTFT/TPOT/latency histograms, cumulative)",
        "max.prom": "timestamped :8001 /metrics snapshots (maxserve_* histograms, cumulative)",
        "k6/": "k6 --summary-export JSON + *.ndjson per-request points (status,timing)",
        "logs/": "engine server logs (decode throughput, batching, errors)",
    },
}
with open(os.path.join(out, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)
PY

echo "==> done: $OUT"
find "$OUT" -type f -exec ls -lh {} \;
