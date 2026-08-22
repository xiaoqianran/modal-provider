from __future__ import annotations

import subprocess
import time
import uuid
from pathlib import Path

import modal

APP_NAME = "modal-3d-trellis.cpp"
BUNDLE_TAG = "trellis.cpp-pynone-cu129-torchnone-sm89-v1"
BUNDLE_URL = (
    "https://github.com/xiaoqianran/modal-build/releases/download/"
    f"{BUNDLE_TAG}/{BUNDLE_TAG}.tar.gz"
)
MODEL_REPO = "ilintar/trellis2-gguf"
MODEL_DIR = "/models"
RUNTIME_DIR = "/opt/trellis"
GPU = "L40S"
PORT = 8080

GEOMETRY_MODELS = (
    "dinov3.gguf",
    "ss_flow.gguf",
    "ss_dec.gguf",
    "shape_flow_512.gguf",
    "shape_flow_1024.gguf",
    "shape_dec.gguf",
)

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-trellis.cpp-f16-geometry", create_if_missing=True)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)

download_image = modal.Image.debian_slim(python_version="3.11").uv_pip_install(
    "huggingface_hub>=0.34,<1"
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.9.1-runtime-ubuntu22.04", add_python="3.11")
    .apt_install("curl", "ca-certificates")
    .uv_pip_install("requests")
    .run_commands(
        f"mkdir -p {RUNTIME_DIR} && curl -fL '{BUNDLE_URL}' | tar -xz -C {RUNTIME_DIR}",
        f"chmod +x {RUNTIME_DIR}/trellis-server {RUNTIME_DIR}/trellis-cli",
    )
    .env({"LD_LIBRARY_PATH": RUNTIME_DIR})
)


@app.function(
    image=download_image,
    volumes={MODEL_DIR: weights},
    cpu=4,
    memory=8192,
    timeout=60 * 60,
    max_containers=1,
)
def sync_weights() -> dict:
    """CPU-only geometry F16 GGUF sync; texture and BiRefNet are intentionally excluded."""
    from huggingface_hub import hf_hub_download

    t0 = time.perf_counter()
    Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)
    for filename in GEOMETRY_MODELS:
        hf_hub_download(MODEL_REPO, filename=filename, local_dir=MODEL_DIR)
    weights.commit()
    total = sum((Path(MODEL_DIR) / name).stat().st_size for name in GEOMETRY_MODELS)
    return {"elapsed_s": time.perf_counter() - t0, "bytes": total, "files": GEOMETRY_MODELS}


@app.cls(
    image=runtime_image,
    gpu=GPU,
    volumes={MODEL_DIR: weights, "/artifacts": artifacts},
    min_containers=0,
    max_containers=1,
    scaledown_window=60,
    timeout=30 * 60,
    startup_timeout=5 * 60,
)
class Model:
    @modal.enter()
    def start(self):
        import requests

        t0 = time.perf_counter()
        self.proc = subprocess.Popen(
            [
                f"{RUNTIME_DIR}/trellis-server",
                "--models",
                MODEL_DIR,
                "--gpu",
                "0",
                "--res",
                "1024",
                "--no-texture",
                "--require-gpu",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
            ]
        )
        health = f"http://127.0.0.1:{PORT}/health"
        for _ in range(100):
            if self.proc.poll() is not None:
                raise RuntimeError(f"trellis-server exited with code {self.proc.returncode}")
            try:
                if requests.get(health, timeout=0.5).ok:
                    self.start_s = time.perf_counter() - t0
                    return
            except requests.RequestException:
                pass
            time.sleep(0.1)
        raise RuntimeError("trellis-server health check timed out")

    @modal.method()
    def generate(self, image_bytes: bytes, seed: int = 42) -> dict:
        import requests

        t0 = time.perf_counter()
        response = requests.post(
            f"http://127.0.0.1:{PORT}/generate",
            files={
                "image": ("input.png", image_bytes, "image/png"),
                "seed": (None, str(seed)),
                "resolution": (None, "1024"),
            },
            timeout=25 * 60,
        )
        response.raise_for_status()
        inference_s = time.perf_counter() - t0

        name = f"trellis.cpp/{uuid.uuid4().hex}.glb"
        path = Path("/artifacts") / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        artifacts.commit()
        return {
            "artifact": name,
            "glb_bytes": len(response.content),
            "server_start_s": self.start_s,
            "inference_s": inference_s,
        }
