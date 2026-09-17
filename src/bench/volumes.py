"""Named Modal Volumes shared by both benchmark stacks."""

import modal

from .settings import BenchConfig


def hf_cache_volume(cfg: BenchConfig) -> modal.Volume:
    """Shared Hugging Face cache — weights download once, both stacks reuse."""
    return modal.Volume.from_name(cfg.volumes.hf_cache, create_if_missing=True)


def max_cache_volume(cfg: BenchConfig) -> modal.Volume:
    """MAX-only cache (MODULAR_HOME): MEF compile artifacts, kernels, etc."""
    return modal.Volume.from_name(cfg.volumes.max_cache, create_if_missing=True)


def results_volume(cfg: BenchConfig) -> modal.Volume:
    """Mounted at /results — in-container /metrics snapshots land here."""
    return modal.Volume.from_name(cfg.volumes.results, create_if_missing=True)
