"""Container image builders for the two benchmark stacks.

Both images get the local ``bench`` package baked in via
``add_local_python_source`` so container-side helpers (readiness probes,
telemetry scraper) are importable there.
"""

from pathlib import Path

import modal

from .settings import (
    HF_CACHE_MOUNT,
    MAX_CACHE_MOUNT,
    RESULTS_MOUNT,
    BenchConfig,
)

_CONFIG_LOCAL = Path(__file__).resolve().parents[1] / "config.yaml"


def _with_bench_source(image: modal.Image) -> modal.Image:
    """Bake the bench package + config into the image.

    Modal may re-import the app module remotely; config.yaml and pyyaml keep
    ``load_config()`` working identically inside the container.
    """
    return (
        image.pip_install("pyyaml")
        .add_local_python_source("bench", copy=True)
        .add_local_file(str(_CONFIG_LOCAL), "/root/config.yaml", copy=True)
    )

# Env vars every benchmark container sees (server-facing knobs; config.yaml is
# also baked in for helpers that load settings remotely).
def _shared_env(cfg: BenchConfig) -> dict[str, str]:
    return {
        "HF_HOME": HF_CACHE_MOUNT,
        "HF_HUB_CACHE": f"{HF_CACHE_MOUNT}/hub",
        "HF_XET_HIGH_PERFORMANCE": "1",
        "BENCH_MODEL": cfg.model.name,
        "BENCH_PORT": str(cfg.server.port),
        "BENCH_RESULTS_DIR": RESULTS_MOUNT,
        "BENCH_METRICS_INTERVAL_S": str(cfg.metrics_interval_s),
    }


def sglang_image(cfg: BenchConfig) -> modal.Image:
    """Stock SGLang release image — vanilla flags only, for engine parity."""
    return _with_bench_source(
        modal.Image.from_registry(cfg.sglang.image)
        .entrypoint([])  # silence chatty logs on container start
        .env(_shared_env(cfg) | {"BENCH_METRICS_URLS": cfg.sglang.metrics_urls[0]})
    )


def max_image(cfg: BenchConfig) -> modal.Image:
    """OSS MAX stack: `max[serve]` wheel from Modular's public nightly index on
    a CUDA 13 base (docker.modular.com rate-limits anonymous image pulls)."""
    return _with_bench_source(
        modal.Image.from_registry(cfg.max.image, add_python="3.12")
        .entrypoint([])
        .env(
            _shared_env(cfg)
            | {
                "MODULAR_HOME": MAX_CACHE_MOUNT,
                "BENCH_METRICS_URLS": ",".join(cfg.max.metrics_urls),
            }
        )
        .uv_pip_install(cfg.max_package, extra_index_url=cfg.max_wheel_index, pre=True)
    )
