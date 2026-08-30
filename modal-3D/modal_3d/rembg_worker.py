"""Direct T4 background preparation for modal-3D.

``process`` preserves the legacy byte-in/mask-out API used by manual local uploads.
``prepare`` is the cloud handoff path: it reads a content-addressed source from the
shared artifact Volume, performs BiRefNet only when needed, and writes canonical
RGBA back to ``client-inputs/`` without routing image bytes through the client.
There is still no CPU gateway or HTTP hop.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import time
from pathlib import Path, PurePosixPath

import modal

from .common import ARTIFACT_VOLUME

APP_NAME = "modal-3d-rembg"
ENGINE = "birefnet-general-lite"
WEIGHT_VOLUME = "modal-3d-birefnet-weights"
ARTIFACT_ROOT = PurePosixPath("/artifacts")
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx"
WEIGHT_ROOT = PurePosixPath("/weights/rembg")
MODEL_PATH = WEIGHT_ROOT / "models" / ENGINE / f"{ENGINE}.onnx"
WEIGHT_MANIFEST = WEIGHT_ROOT / "manifest.json"
MODEL_BYTES = 224_005_088
MODEL_SHA256 = "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name(WEIGHT_VOLUME, create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)

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
    .add_local_python_source("modal_3d")
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_weight_manifest() -> dict[str, object]:
    manifest_path = Path(str(WEIGHT_MANIFEST))
    model_path = Path(str(MODEL_PATH))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
    if not model_path.is_file() or model_path.stat().st_size != MODEL_BYTES:
        raise RuntimeError("BiRefNet weight file is unavailable or truncated")
    actual_sha256 = _sha256(model_path)
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
    model_path = Path(str(MODEL_PATH))
    manifest_path = Path(str(WEIGHT_MANIFEST))
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = model_path.with_name(f".{model_path.name}.{uuid.uuid4().hex}.part")
    try:
        urllib.request.urlretrieve(MODEL_URL, temporary)
        if temporary.stat().st_size != MODEL_BYTES:
            raise RuntimeError(f"unexpected BiRefNet weight size: {temporary.stat().st_size}")
        actual_sha256 = _sha256(temporary)
        if actual_sha256 != MODEL_SHA256:
            raise RuntimeError(f"BiRefNet weight SHA-256 mismatch: {actual_sha256}")
        os.replace(temporary, model_path)
    finally:
        temporary.unlink(missing_ok=True)

    manifest = {
        "model": ENGINE,
        "path": str(MODEL_PATH),
        "bytes": MODEL_BYTES,
        "sha256": MODEL_SHA256,
        "source": MODEL_URL,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    weights.commit()
    return {**manifest, "elapsed_s": time.perf_counter() - started}


@app.cls(
    image=runtime_image,
    gpu="T4",
    volumes={"/weights": weights, str(ARTIFACT_ROOT): artifacts},
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

    def _predict_mask_bytes(self, data: bytes) -> tuple[bytes, list[int], float]:
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
        return (
            output.getvalue(),
            [source.width, source.height],
            round((time.perf_counter() - started) * 1000, 2),
        )

    @modal.method()
    def process(self, data: bytes) -> dict:
        mask_bytes, source_size, elapsed_ms = self._predict_mask_bytes(data)
        return {
            "mask_bytes_b64": base64.b64encode(mask_bytes).decode("ascii"),
            "source_size": source_size,
            "engine": ENGINE,
            "elapsed_ms": elapsed_ms,
        }

    @modal.method()
    def prepare(self, source_path: str) -> dict:
        from modal_3d.conditioning import BackgroundMaskRequired, condition_image

        rel = PurePosixPath(source_path)
        if (
            rel.is_absolute()
            or ".." in rel.parts
            or len(rel.parts) != 4
            or rel.parts[:2] != ("sources", "sha256")
        ):
            raise ValueError("source_path must be a content-addressed source artifact")
        source_sha256 = rel.name.lower()
        if len(source_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in source_sha256):
            raise ValueError("source_path SHA-256 is invalid")
        if rel.parts[2] != source_sha256[:2]:
            raise ValueError("source_path SHA-256 prefix is invalid")
        artifact_root = Path(str(ARTIFACT_ROOT))
        path = artifact_root / Path(*rel.parts)
        if not path.is_file():
            artifacts.reload()
        if not path.is_file():
            raise FileNotFoundError(source_path)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != source_sha256:
            raise ValueError("source artifact SHA-256 mismatch")

        engine = None
        mask_elapsed_ms = None
        try:
            conditioned = condition_image(data)
        except BackgroundMaskRequired:
            mask_bytes, _source_size, mask_elapsed_ms = self._predict_mask_bytes(data)
            conditioned = condition_image(data, mask_bytes)
            engine = ENGINE

        canonical = bytes(conditioned["canonical_bytes"])
        canonical_sha256 = str(conditioned["canonical_sha256"])
        target_rel = PurePosixPath("client-inputs") / f"{canonical_sha256}.png"
        target = artifact_root / Path(*target_rel.parts)
        if (
            not target.is_file()
            or hashlib.sha256(target.read_bytes()).hexdigest() != canonical_sha256
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{os.getpid()}.part")
            try:
                temporary.write_bytes(canonical)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            artifacts.commit()

        evidence_keys = (
            "strategy",
            "source_sha256",
            "canonical_sha256",
            "source_format",
            "source_size",
            "foreground_bbox",
            "foreground_ratio",
            "canonical_size",
        )
        evidence = {key: conditioned[key] for key in evidence_keys if key in conditioned}
        if engine is not None:
            evidence["engine"] = engine
        if mask_elapsed_ms is not None:
            evidence["mask_elapsed_ms"] = mask_elapsed_ms
        return {
            "path": target_rel.as_posix(),
            "source_sha256": source_sha256,
            "canonical_sha256": canonical_sha256,
            "canonical_bytes": len(canonical),
            "conditioning": evidence,
        }
