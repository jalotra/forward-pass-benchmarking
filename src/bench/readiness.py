"""Container-side readiness helpers — stdlib only (urllib), no third-party
imports, so they run in any benchmark image without extra installs.
"""

import json
import subprocess
import time
import urllib.error
import urllib.request


def wait_for_health(
    process: subprocess.Popen,
    base_url: str,
    health_path: str,
    timeout_s: float,
    name: str,
) -> None:
    """Poll ``base_url + health_path`` until 200, or die fast on process exit."""
    deadline = time.time() + timeout_s
    url = f"{base_url}{health_path}"
    while time.time() < deadline:
        if (rc := process.poll()) is not None:
            raise RuntimeError(f"{name} exited during startup with code {rc}")
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(5)
    raise TimeoutError(f"{name} not healthy within {timeout_s}s")


def prewarm_weights(model: str, revision: str) -> None:
    """Download the pinned model revision into the shared HF cache volume.

    Soft-fails: if the image's python lacks ``huggingface_hub`` the engine
    downloads weights on serve anyway (possibly unpinned — check logs).
    """
    code = (
        "from huggingface_hub import snapshot_download;"
        f"snapshot_download({model!r}, revision={revision!r})"
    )
    subprocess.run(["python", "-c", code], check=False, timeout=1800)


def warmup_chat(base_url: str, model: str, rounds: int = 3, max_tokens: int = 16) -> None:
    """Send a few chat completions so caches/graphs are hot before load hits."""
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "Hello, how are you?"}],
            "max_tokens": max_tokens,
        }
    ).encode()
    for _ in range(rounds):
        req = urllib.request.Request(
            f"{base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
