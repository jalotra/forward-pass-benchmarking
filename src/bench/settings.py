"""Typed view over ``src/config.yaml``.

Loaded locally at ``modal deploy`` time — this module is *not* imported inside
the benchmark containers (they receive what they need via env vars on the
image), so PyYAML is only a local deploy-time dependency.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@dataclass(frozen=True)
class ModelConfig:
    name: str
    revision: str
    max_length: int


@dataclass(frozen=True)
class HardwareConfig:
    gpu: str
    compute_region: str
    routing_region: str


@dataclass(frozen=True)
class ServerConfig:
    port: int
    min_containers: int
    max_containers: int
    startup_timeout_min: int
    exit_grace_period_s: int


@dataclass(frozen=True)
class EngineConfig:
    """Per-engine deployment details."""

    image: str
    app_name: str
    health_path: str
    metrics_urls: list[str]


@dataclass(frozen=True)
class VolumeConfig:
    hf_cache: str
    max_cache: str
    results: str


@dataclass(frozen=True)
class BenchConfig:
    model: ModelConfig
    hardware: HardwareConfig
    server: ServerConfig
    sglang: EngineConfig
    max: EngineConfig
    volumes: VolumeConfig
    metrics_interval_s: int
    max_wheel_index: str
    max_package: str


def load_config(path: Path = CONFIG_PATH) -> BenchConfig:
    raw = yaml.safe_load(path.read_text())

    return BenchConfig(
        model=ModelConfig(**raw["model"]),
        hardware=HardwareConfig(**raw["hardware"]),
        server=ServerConfig(**raw["server"]),
        sglang=EngineConfig(
            image=raw["sglang"]["image"],
            app_name=raw["sglang"]["app_name"],
            health_path=raw["sglang"]["health_path"],
            metrics_urls=[raw["sglang"]["metrics_url"]],
        ),
        max=EngineConfig(
            image=raw["max"]["base_image"],
            app_name=raw["max"]["app_name"],
            health_path=raw["max"]["health_path"],
            metrics_urls=list(raw["max"]["metrics_urls"]),
        ),
        volumes=VolumeConfig(**raw["volumes"]),
        metrics_interval_s=raw["telemetry"]["interval_s"],
        max_wheel_index=raw["max"]["wheel_index"],
        max_package=raw["max"]["package"],
    )


# Paths inside the benchmark containers.
HF_CACHE_MOUNT = "/cache/huggingface"
MAX_CACHE_MOUNT = "/cache/modular"
RESULTS_MOUNT = "/results"
