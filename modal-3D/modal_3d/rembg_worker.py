"""Direct T4 background-mask worker used by the local client.

This app performs only the expensive BiRefNet mask prediction. The VPS/client
calls ``RemBgWorker.process`` directly, then refines the mask and builds the
canonical RGBA locally. There is deliberately no CPU ``condition`` function,
HTTP gateway, artifact routing, or source-input namespace in this app.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from pathlib import Path

import modal

APP_NAME = "modal-3d-rembg"
ENGINE = "birefnet-general-lite"
WEIGHT_VOLUME = "modal-3d-birefnet-weights"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx"
WEIGHT_ROOT = Path("/weights/rembg")
MODEL_PATH = WEIGHT_ROOT / "models" / ENGINE / f"{ENGINE}.onnx"
WEIGHT_MANIFEST = WEIGHT_ROOT / "manifest.json"
MODEL_BYTES = 224_005_088
MODEL_SHA256 = "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name(WEIGHT_VOLUME, create_if_missing=True)

runtime_image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install(
        "Pillow==12.1.0",
        "numpy==2.3.5",
        "scipy==1.16.3",
        "rembg==2.0.81",
        "onnxruntime-gpu==1.25.1",
        "nvidia-cublas-cu12==12.9.2.10",
        "nvidia-cuda-runtime-cu12==12.9.79",
        "nvidia-cudnn-cu12==9.24.0.43",
        "nvidia-cufft-cu12==11.4.1.4",
        "nvidia-curand-cu12==10.3.10.19",
    )
    .env({"REMBG_HOME": str(WEIGHT_ROOT), "PYTHONUNBUFFERED": "1"})
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_weight_manifest() -> dict[str, object]:
    try:
        manifest = json.loads(WEIGHT_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("BiRefNet weight manifest is unavailable") from exc
    expected = {
        "model": ENGINE,
        "path": str(MODEL_PATH),
        "bytes": MODEL_BYTES,
        "sha256": MODEL_SHA256,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RuntimeError("BiRefNet weight manifest is incompatible")
    if not MODEL_PATH.is_file() or MODEL_PATH.stat().st_size != MODEL_BYTES:
        raise RuntimeError("BiRefNet weight file is unavailable or truncated")
    actual_sha256 = _sha256(MODEL_PATH)
    if actual_sha256 != MODEL_SHA256:
        raise RuntimeError(f"BiRefNet weight SHA-256 mismatch: {actual_sha256}")
    return manifest


@app.function(
    image=modal.Image.debian_slim(python_version="3.11"),
    volumes={"/weights": weights},
    cpu=2,
    memory=4096,
    timeout=20 * 60,
    max_containers=1,
)
def sync_weights() -> dict:
    """CPU-only deployment helper; never used by the request path."""
    import os
    import urllib.request
    import uuid

    started = time.perf_counter()
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MODEL_PATH.with_name(f".{MODEL_PATH.name}.{uuid.uuid4().hex}.part")
    try:
        urllib.request.urlretrieve(MODEL_URL, temporary)
        if temporary.stat().st_size != MODEL_BYTES:
            raise RuntimeError(f"unexpected BiRefNet weight size: {temporary.stat().st_size}")
        actual_sha256 = _sha256(temporary)
        if actual_sha256 != MODEL_SHA256:
            raise RuntimeError(f"BiRefNet weight SHA-256 mismatch: {actual_sha256}")
        os.replace(temporary, MODEL_PATH)
    finally:
        temporary.unlink(missing_ok=True)

    manifest = {
        "model": ENGINE,
        "path": str(MODEL_PATH),
        "bytes": MODEL_BYTES,
        "sha256": MODEL_SHA256,
        "source": MODEL_URL,
    }
    WEIGHT_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    weights.commit()
    return {**manifest, "elapsed_s": time.perf_counter() - started}


@app.cls(
    image=runtime_image,
    gpu="T4",
    volumes={"/weights": weights},
    timeout=10 * 60,
    scaledown_window=120,
    max_containers=1,
)
class RemBgWorker:
    @modal.enter()
    def load(self) -> None:
        _verify_weight_manifest()

        import onnxruntime as ort

        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls(cuda=True, cudnn=True, directory="")

        from rembg.session_factory import new_session

        self.session = new_session(
            ENGINE,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )

    @modal.method()
    def process(self, data: bytes) -> dict:
        from PIL import Image, ImageOps

        if not data:
            raise ValueError("source image is empty")
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("source image exceeds 20 MiB")

        started = time.perf_counter()
        with Image.open(io.BytesIO(data)) as opened:
            source = ImageOps.exif_transpose(opened).convert("RGB")

        prediction = self.session.predict(source)
        if not prediction:
            raise RuntimeError("rembg returned no foreground alpha mask")
        mask = prediction[0]
        if mask.mode != "L":
            mask = mask.convert("L")
        if mask.size != source.size:
            mask = mask.resize(source.size, Image.Resampling.LANCZOS)

        output = io.BytesIO()
        mask.save(output, format="PNG", compress_level=6)
        return {
            "mask_bytes_b64": base64.b64encode(output.getvalue()).decode("ascii"),
            "source_size": [source.width, source.height],
            "engine": ENGINE,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
