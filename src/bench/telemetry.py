"""In-container Prometheus metrics scraper.

Run as ``python -m bench.telemetry`` — spawned by the server classes in
``src/apps/``. Env-configured (no argparse, per project rules):

- ``BENCH_METRICS_URLS``       comma-separated /metrics URLs to try in order
- ``BENCH_METRICS_OUT``        file to append timestamped snapshots to
                               (should live on the mounted results Volume)
- ``BENCH_METRICS_INTERVAL_S`` scrape cadence in seconds (default 5)

Output format: repeated ``# @timestamp <iso8601> <url>`` headers followed by the
raw /metrics text, so post-analysis can diff cumulative histogram counters.
Stdlib only — runs in any image.
"""

import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default).strip()
    return value


def scrape_once(urls: list[str]) -> tuple[str, str] | None:
    """Return (url, body) for the first reachable metrics endpoint."""
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    return url, resp.read().decode(errors="replace")
        except (urllib.error.URLError, OSError):
            continue
    return None


def main() -> int:
    urls = [u for u in _env("BENCH_METRICS_URLS").split(",") if u]
    out_path = _env("BENCH_METRICS_OUT", "/results/metrics.prom")
    interval = float(_env("BENCH_METRICS_INTERVAL_S", "5"))

    if not urls:
        print("telemetry: BENCH_METRICS_URLS is empty, nothing to scrape", file=sys.stderr)
        return 2

    print(f"telemetry: scraping {urls} every {interval}s -> {out_path}")
    while True:
        snapshot = scrape_once(urls)
        ts = datetime.now(timezone.utc).isoformat()
        with open(out_path, "a") as f:
            if snapshot is None:
                f.write(f"# @timestamp {ts} UNREACHABLE\n\n")
            else:
                url, body = snapshot
                f.write(f"# @timestamp {ts} {url}\n{body}\n")
            f.flush()
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
