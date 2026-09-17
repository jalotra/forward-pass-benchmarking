#!/usr/bin/env python
"""Slice benchmark data to "200 windows" (periods where requests returned
HTTP 200), normalize all latencies to milliseconds, and emit seaborn plots
+ a summary table.

Reads a metrics dir produced by scripts/collect_metrics.sh:

    metrics/<model>/<stamp>/
      sglang.prom   max.prom      # timestamped /metrics snapshots
      k6/*.ndjson                 # per-request k6 --out json points
      k6/*.json                   # k6 summary exports

Writes into the same dir:

      plots/*.png   tables/summary.csv

Run:  METRICS_DIR=metrics/<model>/<stamp> .venv/bin/python scripts/analyze_metrics.py
      (defaults to the newest metrics/<model>/<stamp>)
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

sns.set_theme(style="whitegrid", context="talk")
plt.rcParams["figure.dpi"] = 140

STACKS = {"sglang": "#1f77b4", "max": "#d62728"}

# --------------------------------------------------------------------------
# Discovery / parsing
# --------------------------------------------------------------------------

def metrics_dir() -> Path:
    if os.environ.get("METRICS_DIR"):
        return Path(os.environ["METRICS_DIR"])
    dirs = sorted(Path("metrics").glob("*/*/"), key=lambda p: p.stat().st_mtime)
    if not dirs:
        sys.exit("no metrics/<model>/<stamp>/ dir found — run collect_metrics.sh first")
    return dirs[-1]


def parse_prom(path: Path) -> list[dict]:
    """-> [{ts, metrics: {(name, labels_key): {le: value} | {None: value}}}]"""
    snaps, cur = [], None
    for line in path.read_text(errors="replace").splitlines():
        m = re.match(r"# @timestamp (\S+)", line)
        if m:
            cur = {"ts": datetime.fromisoformat(m.group(1)), "metrics": {}}
            snaps.append(cur)
            continue
        if cur is None or line.startswith("#") or not line.strip():
            continue
        m = re.match(r"([a-zA-Z_:][\w:]*)(?:\{([^}]*)\})?\s+([\d.eE+naNA-]+)", line)
        if not m:
            continue
        name, labelstr, val = m.groups()
        labels = dict(re.findall(r'(\w+)="([^"]*)"', labelstr or ""))
        try:
            v = float(val)
        except ValueError:
            continue
        le = labels.pop("le", None)
        key = (name, tuple(sorted(labels.items())))
        cur["metrics"].setdefault(key, {})[le] = v
    return snaps


def load_ndjson(path: Path) -> pd.DataFrame:
    """k6 --out json points -> DataFrame[ts, metric, status, value_ms]."""
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("type") != "Point":
            continue
        metric = d["metric"]
        if metric not in ("http_req_duration", "e2e_ms", "completion_tps"):
            continue
        data = d["data"]
        rows.append({
            "ts": datetime.fromisoformat(data["time"].replace("Z", "+00:00")),
            "metric": metric,
            "status": data.get("tags", {}).get("status", "?"),
            "value": float(data["value"]),
        })
    return pd.DataFrame(rows)

# --------------------------------------------------------------------------
# 200-window detection
# --------------------------------------------------------------------------

STAGE_VUS = [1, 2, 4, 8, 16, 32]
STAGE_S = 100


def ok_window(df: pd.DataFrame) -> tuple[datetime, datetime]:
    """Longest contiguous span where >=95% of per-second responses are 200."""
    reqs = df[df.metric == "http_req_duration"].copy()
    if reqs.empty:
        raise ValueError("no requests in ndjson")
    reqs["sec"] = reqs.ts.dt.floor("1s")
    per_sec = reqs.groupby("sec").status.apply(lambda s: (s == "200").mean())
    good = per_sec[per_sec >= 0.95]
    if good.empty:  # fallback: use the densest 200 region
        t200 = reqs[reqs.status == "200"].ts
        return t200.min(), t200.max()
    # merge into contiguous runs (gap <= 10s), keep the longest
    runs, start, prev = [], good.index[0], good.index[0]
    for t in good.index[1:]:
        if (t - prev).total_seconds() > 10:
            runs.append((start, prev))
            start = t
        prev = t
    runs.append((start, prev))
    a, b = max(runs, key=lambda r: (r[1] - r[0]).total_seconds())
    return a, b + pd.Timedelta(seconds=1)


def align_windows(dfs: dict[str, pd.DataFrame], windows: dict[str, tuple]) -> dict[str, tuple]:
    """Align each stack's window to the same VU stages: start both at the
    highest common stage index each window covers (fair comparison)."""
    if len(windows) < 2:
        return windows
    starts = {}
    for stack, df in dfs.items():
        if stack not in windows or df.empty:
            continue
        run_start = df.ts.min()
        stage0 = int((windows[stack][0] - run_start).total_seconds() // STAGE_S)
        stage1 = int((windows[stack][1] - run_start).total_seconds() // STAGE_S)
        starts[stack] = (run_start, stage0, stage1)
    if len(starts) < 2:
        return windows, 0, 5
    common = max(s[1] for s in starts.values())
    common_end = min(s[2] for s in starts.values())
    out = {}
    for stack, (rs, _s0, _s1) in starts.items():
        out[stack] = (rs + pd.Timedelta(seconds=common * STAGE_S),
                      rs + pd.Timedelta(seconds=(common_end + 1) * STAGE_S))
    return out, common, common_end

# --------------------------------------------------------------------------
# Histogram helpers (all latencies normalized to ms)
# --------------------------------------------------------------------------

def snap_near(snaps, t, side):
    """Snapshot nearest to t on the given side ('before'/'after')."""
    seq = [s for s in snaps if (s["ts"] <= t if side == "before" else s["ts"] >= t)]
    return (seq[-1] if side == "before" else seq[0]) if seq else None


def hist_diff(snaps, name_frag, t0, t1, scale=1.0):
    """Diff a cumulative histogram across [t0,t1] -> DataFrame[le_ms, count].
    Start snapshot is the first AT/AFTER t0 — picking the one before t0 could
    cross a container-restart gap and subtract stale cumulative counts."""
    a, b = snap_near(snaps, t0, "after"), snap_near(snaps, t1, "before")
    if not a or not b:
        return None
    key = next((k for k in b["metrics"] if name_frag in k[0] and k[0].endswith("_bucket")), None)
    if key is None:
        return None
    # missing counter in the start snapshot == zero (lazy registration)
    end, start = b["metrics"][key], a["metrics"].get(key, {})
    rows = []
    for le, v in end.items():
        if le is None or le == "+Inf":
            continue
        rows.append((float(le) * scale, max(0.0, v - start.get(le, 0.0))))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["le_ms", "cum"]).sort_values("le_ms")
    df["count"] = df["cum"].diff().fillna(df["cum"])
    return df


def cdf_from_hist(df: pd.DataFrame) -> pd.DataFrame:
    """Approximate ECDF points (x=ms, y=cum fraction) from bucket counts."""
    xs, ys = [0.0], [0.0]
    total = df["count"].sum()
    if total <= 0:
        return pd.DataFrame({"x": [], "y": []})
    prev_x, cum = 0.0, 0.0
    for _, r in df.iterrows():
        # spread bucket mass linearly between prev bound and le bound
        n = max(int(r["count"]), 1)
        for i in range(1, n + 1):
            cum += 1
            xs.append(prev_x + (r["le_ms"] - prev_x) * i / n)
            ys.append(cum / total)
        prev_x = r["le_ms"]
    return pd.DataFrame({"x": xs, "y": ys})


def quantile_from_hist(df: pd.DataFrame, q: float) -> float | None:
    cdf = cdf_from_hist(df)
    if cdf.empty:
        return None
    idx = (cdf["y"] - q).abs().idxmin()
    return float(cdf.loc[idx, "x"])


def gauge_series(snaps, name_frag, t0, t1):
    """Time series of a gauge/counter within the window."""
    pts = []
    for s in snaps:
        if not (t0 <= s["ts"] <= t1):
            continue
        for (name, _lbls), vals in s["metrics"].items():
            if name_frag in name and None in vals and not name.endswith(("_bucket", "_sum", "_count")):
                pts.append((s["ts"], vals[None]))
    if not pts:
        return None
    df = pd.DataFrame(pts, columns=["ts", "v"]).sort_values("ts")
    df["t"] = (df.ts - df.ts.iloc[0]).dt.total_seconds()
    return df


def counter_rate(snaps, name_frag, t0, t1):
    """Rate (per-s) of a cumulative counter within the window."""
    s = gauge_series(snaps, name_frag, t0, t1)
    if s is None or len(s) < 2:
        return None
    s = s.copy()
    s["rate"] = s["v"].diff() / s["ts"].diff().dt.total_seconds()
    return s.dropna()

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    root = metrics_dir()
    out_p, out_t = root / "plots", root / "tables"
    out_p.mkdir(parents=True, exist_ok=True)
    out_t.mkdir(parents=True, exist_ok=True)
    print(f"analyzing {root}")

    prom, k6 = {}, {}
    for stack in STACKS:
        p = root / f"{stack}.prom"
        prom[stack] = parse_prom(p) if p.exists() else []
        nd = sorted((root / "k6").glob(f"*{stack}*.ndjson")) or sorted((root / "k6").glob("*.ndjson"))
        k6[stack] = load_ndjson(nd[-1]) if nd else pd.DataFrame()

    windows = {}
    for stack, df in k6.items():
        if df.empty:
            continue
        windows[stack] = ok_window(df)
    raw_windows = dict(windows)
    windows, common_s0, common_s1 = align_windows(k6, windows)  # same VU stages on both stacks
    for stack, (a, b) in windows.items():
        df = k6[stack]
        n200 = int(((df[df.metric == "http_req_duration"].status == "200")
                    & (df.ts >= a) & (df.ts <= b)).sum())
        rs = df.ts.min()
        s0 = int((a - rs).total_seconds() // STAGE_S)
        s1 = int((b - rs).total_seconds() // STAGE_S)
        print(f"{stack}: 200-window {a:%H:%M:%S}-{b:%H:%M:%S}Z ({(b-a).total_seconds():.0f}s) "
              f"stages {STAGE_VUS[min(s0,5)]}-{STAGE_VUS[min(s1,5)]}VU | {n200} ok reqs in window "
              f"(raw: {raw_windows[stack][0]:%H:%M:%S}-{raw_windows[stack][1]:%H:%M:%S})")

    # ---- summary table ----------------------------------------------------
    rows = []
    HIST = {  # metric -> (sglang frag, max frag, sglang scale s->ms)
        "TTFT_ms": ("time_to_first_token_seconds", "time_to_first_token_milliseconds", 1000),
        "TPOT_ms": ("inter_token_latency_seconds", "time_per_output_token_milliseconds", 1000),
        "ITL_ms": ("inter_token_latency_seconds", "itl_milliseconds", 1000),
        "E2E_ms": ("e2e_request_latency_seconds", "request_time_milliseconds", 1000),
    }
    cdfs = {m: {} for m in HIST}
    for metric, (sg, mx, scale) in HIST.items():
        for stack, frag in (("sglang", sg), ("max", mx)):
            if stack not in windows or not prom[stack]:
                continue
            sc = scale if stack == "sglang" else 1.0  # sglang s -> ms
            h = hist_diff(prom[stack], frag, *windows[stack], scale=sc)
            if h is None:
                continue
            cdfs[metric][stack] = cdf_from_hist(h)
            row = {"metric": metric, "stack": stack}
            for q in (0.5, 0.9, 0.99):
                row[f"p{int(q*100)}"] = round(quantile_from_hist(h, q) or 0, 1)
            row["n"] = int(h["count"].sum())
            rows.append(row)
    summary = pd.DataFrame(rows)
    summary.to_csv(out_t / "summary.csv", index=False)
    print(summary.to_string(index=False))

    # ---- panel drawers (shared by individual PNGs and the dashboard) ---------
    def p_hist_cdf(ax, metric: str) -> bool:
        drew = False
        for stack, cdf in cdfs.get(metric, {}).items():
            if not cdf.empty:
                sns.lineplot(data=cdf, x="x", y="y", label=stack, ax=ax, color=STACKS[stack], lw=2)
                drew = True
        if drew:
            ax.set(xlabel=f"{metric[:-3]} (ms)", ylabel="CDF", title=f"{metric[:-3]} distribution")
            ax.set_xscale("log")
        return drew

    def p_client_e2e(ax) -> bool:
        drew = False
        for stack, df in k6.items():
            if df.empty or stack not in windows:
                continue
            r = df[(df.metric == "http_req_duration") & (df.status == "200")
                   & (df.ts >= windows[stack][0]) & (df.ts <= windows[stack][1])]
            if len(r):
                sns.ecdfplot(x=r["value"], label=stack, ax=ax, color=STACKS[stack], lw=2)
                drew = True
        if drew:
            ax.set(xlabel="client E2E (ms)", ylabel="CDF", title="Client E2E — 200s")
            ax.set_xscale("log")
        return drew

    def p_vu_box(ax) -> bool:
        if alld is None or alld.empty:
            return False
        sns.boxplot(data=alld, x="stage", y="value", hue="stack", palette=STACKS, ax=ax, showfliers=False)
        ax.set(xlabel="concurrent VUs", ylabel="E2E (ms)", title="E2E vs concurrency")
        return True

    def p_series(ax, title, ylabel, series) -> bool:
        drew = False
        for stack, frag, mode in series:
            if stack not in windows or not prom[stack]:
                continue
            df = counter_rate(prom[stack], frag, *windows[stack]) if mode == "rate" else gauge_series(prom[stack], frag, *windows[stack])
            if df is None or df.empty:
                continue
            y = df["rate"] if mode == "rate" else df["v"]
            mult = mode if isinstance(mode, float) else 1.0
            sns.lineplot(x=df["t"], y=y * mult, label=stack, ax=ax, color=STACKS[stack], lw=1.8)
            drew = True
        if drew:
            ax.set(xlabel="s into window", ylabel=ylabel, title=title)
        return drew

    def p_tps_ecdf(ax) -> bool:
        drew = False
        for stack, df in k6.items():
            if df.empty or stack not in windows:
                continue
            r = df[(df.metric == "completion_tps") & (df.ts >= windows[stack][0]) & (df.ts <= windows[stack][1])]
            if len(r):
                sns.ecdfplot(x=r["value"], label=stack, ax=ax, color=STACKS[stack], lw=2)
                drew = True
        if drew:
            ax.set(xlabel="tok/s per request", title="Decode speed — 200s")
        return drew

    # ---- latency vs VU frame --------------------------------------------------
    stage_map = [1, 2, 4, 8, 16, 32]
    frames = []
    for stack, df in k6.items():
        if df.empty or stack not in windows:
            continue
        a, b = windows[stack]
        r = df[(df.metric == "http_req_duration") & (df.status == "200") & (df.ts >= a) & (df.ts <= b)].copy()
        if r.empty:
            continue
        # absolute stage index: window starts at common_s0 — label by real VU
        r["stage"] = (common_s0 + (r.ts - a).dt.total_seconds() // 100).clip(0, 5).astype(int).map(lambda i: stage_map[i])
        r["stack"] = stack
        frames.append(r[["value", "stage", "stack"]])
    alld = pd.concat(frames) if frames else None
    if alld is not None:
        per_stage = (alld.groupby(["stack", "stage"])["value"]
                     .agg(n="count", p50=lambda s: s.quantile(.5), p90=lambda s: s.quantile(.9),
                          p99=lambda s: s.quantile(.99), mean="mean")
                     .round(1).reset_index())
        per_stage.to_csv(out_t / "e2e_per_stage.csv", index=False)
        print(per_stage.to_string(index=False))

    TS = [
        ("throughput_ts", "Engine output throughput", "tok/s",
         [("sglang", "gen_throughput", None), ("max", "batch_generation_throughput_tokens_per_second", None)]),
        ("tokens_out_ts", "Output token rate", "tok/s",
         [("sglang", "generation_tokens_total", "rate"), ("max", "num_output_tokens_total", "rate")]),
        ("batch_ts", "Concurrent reqs in engine", "requests",
         [("sglang", "num_running_reqs", None), ("max", "num_requests_running", None)]),
        ("queue_ts", "Queued requests", "requests",
         [("sglang", "num_queue_reqs", None), ("max", "num_requests_queued", None)]),
        ("kv_ts", "KV cache occupancy", "%",
         [("sglang", "token_usage", 100.0), ("max", "cache_used_kv_pct_percent", 1.0)]),
    ]

    # ---- panel registry: (filename-stem, draw-fn) — dashboard reuses this ----
    PANELS = [
        ("ttft_ms_cdf", lambda ax: p_hist_cdf(ax, "TTFT_ms")),
        ("tpot_ms_cdf", lambda ax: p_hist_cdf(ax, "TPOT_ms")),
        ("itl_ms_cdf", lambda ax: p_hist_cdf(ax, "ITL_ms")),
        ("e2e_ms_cdf", lambda ax: p_hist_cdf(ax, "E2E_ms")),
        ("client_e2e_cdf", p_client_e2e),
        ("latency_vs_vu", p_vu_box),
        ("completion_tps_cdf", p_tps_ecdf),
    ] + [(stem, (lambda s=s, t=t, y=y: (lambda ax: p_series(ax, t, y, s)))()) for stem, t, y, s in TS]

    # ---- individual PNGs ------------------------------------------------------
    for stem, draw in PANELS:
        fig, ax = plt.subplots(figsize=(8, 5))
        if draw(ax):
            fig.tight_layout()
            fig.savefig(out_p / f"{stem}.png")
        plt.close(fig)

    # ---- combined dashboard (3x4 grid) ----------------------------------------
    fig, axes = plt.subplots(3, 4, figsize=(24, 15), constrained_layout=True)
    for ax, (stem, draw) in zip(axes.ravel(), PANELS):
        if not draw(ax):
            ax.set_visible(False)
    for ax in axes.ravel()[len(PANELS):]:
        ax.set_visible(False)
    gpu = "GPU"
    if (root / "manifest.json").exists():
        gpu = json.loads((root / "manifest.json").read_text()).get("hardware", {}).get("gpu", "GPU")
    fig.suptitle(f"MAX vs SGLang — {root.parent.name} on {gpu} — 200 windows only", fontsize=18)
    fig.savefig(out_p / "dashboard.png")
    plt.close(fig)

    print(f"\nplots -> {out_p}")
    for f in sorted(out_p.glob("*.png")):
        print("  ", f.name)


if __name__ == "__main__":
    main()
