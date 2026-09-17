"""MAX (open-source) stack — Modal deployment entrypoint.

Deploy:  PYTHONPATH=src .venv/bin/modal deploy src/apps/max_server.py
Smoke:   curl $URL/v1/chat/completions -d '{...}'

Uses the official `max-nvidia-full` image which ships the `max` CLI; `max serve`
launches the OpenAI-compatible endpoint (api_server.py in third_party/modular).
"""

import os
import shutil
import subprocess
import sys

import modal

from bench.images import max_image
from bench.readiness import prewarm_weights, wait_for_health, warmup_chat
from bench.settings import (
    HF_CACHE_MOUNT,
    MAX_CACHE_MOUNT,
    RESULTS_MOUNT,
    load_config,
)
from bench.volumes import hf_cache_volume, max_cache_volume, results_volume

cfg = load_config()
BASE_URL = f"http://127.0.0.1:{cfg.server.port}"

app = modal.App(name=cfg.max.app_name)


@app.server(
    image=max_image(cfg),
    gpu=cfg.hardware.gpu,
    volumes={
        HF_CACHE_MOUNT: hf_cache_volume(cfg),
        MAX_CACHE_MOUNT: max_cache_volume(cfg),
        RESULTS_MOUNT: results_volume(cfg),
    },
    compute_region=cfg.hardware.compute_region,
    routing_region=cfg.hardware.routing_region,
    min_containers=cfg.server.min_containers,
    max_containers=cfg.server.max_containers,
    startup_timeout=cfg.server.startup_timeout_min * 60,
    port=cfg.server.port,
    exit_grace_period=cfg.server.exit_grace_period_s,
    unauthenticated=True,
    # Tell the autoscaler this single container is meant to take high
    # concurrency — otherwise it can misread it as idle and scale down
    # mid-benchmark (observed: container killed under load → 503 flood).
    target_concurrency=256,
)
class Max:
    @modal.enter()
    def start(self) -> None:
        prewarm_weights(cfg.model.name, cfg.model.revision)

        max_bin = shutil.which("max")
        if max_bin is None:
            raise RuntimeError("`max` CLI not on PATH in the max image")

        # Minimal flags per Modular's serve guidance: GPU + dtype + endpoints
        # auto-detect. Only max-length is set explicitly (parity with the
        # SGLang stack's --context-length).
        cmd = [
            max_bin,
            "serve",
            "--model",
            cfg.model.name,
            "--max-length",
            str(cfg.model.max_length),
        ]
        self.server = subprocess.Popen(cmd)

        wait_for_health(
            self.server,
            BASE_URL,
            cfg.max.health_path,
            timeout_s=cfg.server.startup_timeout_min * 60,
            name="max",
        )
        warmup_chat(BASE_URL, cfg.model.name)

        self.scraper = subprocess.Popen(
            [sys.executable, "-m", "bench.telemetry"],
            env={
                **os.environ,
                "BENCH_METRICS_OUT": f"{RESULTS_MOUNT}/max.prom",
            },
        )

    @modal.exit()
    def stop(self) -> None:
        self.scraper.terminate()
        self.server.terminate()
