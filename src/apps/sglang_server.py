"""SGLang baseline stack — Modal deployment entrypoint.

Deploy:  PYTHONPATH=src .venv/bin/modal deploy src/apps/sglang_server.py
Smoke:   curl $URL/v1/chat/completions -d '{...}'

Vanilla SGLang on NVIDIA (CUDA + Triton kernels) — no speculative decoding or
exotic flags, to keep engine parity with the MAX stack.
"""

import os
import subprocess
import sys

import modal

from bench.images import sglang_image
from bench.readiness import prewarm_weights, wait_for_health, warmup_chat
from bench.settings import HF_CACHE_MOUNT, RESULTS_MOUNT, load_config
from bench.volumes import hf_cache_volume, results_volume

cfg = load_config()
BASE_URL = f"http://127.0.0.1:{cfg.server.port}"

app = modal.App(name=cfg.sglang.app_name)


@app.server(
    image=sglang_image(cfg),
    gpu=cfg.hardware.gpu,
    volumes={
        HF_CACHE_MOUNT: hf_cache_volume(cfg),
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
class SGLang:
    @modal.enter()
    def start(self) -> None:
        prewarm_weights(cfg.model.name, cfg.model.revision)

        cmd = [
            "python",
            "-m",
            "sglang.launch_server",
            "--model-path",
            cfg.model.name,
            "--revision",
            cfg.model.revision,
            "--served-model-name",
            cfg.model.name,
            "--host",
            "0.0.0.0",
            "--port",
            str(cfg.server.port),
            "--context-length",
            str(cfg.model.max_length),
            "--enable-metrics",
        ]
        self.server = subprocess.Popen(cmd)

        wait_for_health(
            self.server,
            BASE_URL,
            cfg.sglang.health_path,
            timeout_s=cfg.server.startup_timeout_min * 60,
            name="sglang",
        )
        warmup_chat(BASE_URL, cfg.model.name)

        self.scraper = subprocess.Popen(
            [sys.executable, "-m", "bench.telemetry"],
            env={
                **os.environ,
                "BENCH_METRICS_OUT": f"{RESULTS_MOUNT}/sglang.prom",
            },
        )

    @modal.exit()
    def stop(self) -> None:
        self.scraper.terminate()
        self.server.terminate()
