"""Cloud rembg background-removal gateway (T4 GPU).

Runs BiRefNet background removal on a T4 GPU. The legacy `/preprocess`
endpoint still returns only the original-size alpha mask for compatibility.
Provider-internal `condition()` owns automatic mask prediction, refinement,
foreground crop/letterbox, and the canonical RGBA worker input.

The 224 MB BiRefNet ONNX model is prepared by `modal-build` in a named Volume.
Runtime startup verifies the pinned manifest and SHA-256 before constructing the
ONNX session. No model download is allowed in the runtime image or cold start.

Contract:

    POST /preprocess  (body: raw PNG/JPEG/WebP bytes)
        -> {
             "mask_bytes_b64": base64 L-mode PNG (original size alpha mask),
             "source_size": [w, h],
             "engine": "birefnet-general-lite",
           }
"""

import base64
import hashlib
import io
import json
import os
import time
import uuid
from pathlib import Path

import modal

from .common import ARTIFACT_ROOT, validate_canonical_input
from .conditioning import BackgroundMaskRequired, condition_image

APP_NAME = "modal-3d-rembg"
ENGINE = "birefnet-general-lite"
WEIGHT_VOLUME = "modal-3d-birefnet-weights"
WEIGHT_ROOT = Path("/weights/rembg")
MODEL_PATH = WEIGHT_ROOT / "models" / ENGINE / f"{ENGINE}.onnx"
WEIGHT_MANIFEST = WEIGHT_ROOT / "manifest.json"
MODEL_BYTES = 224_005_088
MODEL_SHA256 = "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333"

app = modal.App(APP_NAME)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)
weights = modal.Volume.from_name(WEIGHT_VOLUME)

conditioning_image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install(
        "fastapi==0.116.1",
        "Pillow==12.1.0",
        "numpy==2.3.5",
        "scipy==1.16.3",
    )
    .env({"PYTHONUNBUFFERED": "1"})
)

rembg_image = (
    conditioning_image.uv_pip_install(
        "rembg==2.0.81",
        "onnxruntime-gpu==1.25.1",
        "nvidia-cublas-cu12==12.9.2.10",
        "nvidia-cuda-runtime-cu12==12.9.79",
        "nvidia-cudnn-cu12==9.24.0.43",
        "nvidia-cufft-cu12==11.4.1.4",
        "nvidia-curand-cu12==10.3.10.19",
    ).env({"REMBG_HOME": str(WEIGHT_ROOT)})
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


@app.cls(
    image=rembg_image,
    gpu="T4",
    volumes={"/weights": weights},
    timeout=10 * 60,
    scaledown_window=120,
)
class RemBgWorker:
    @modal.enter()
    def load(self) -> None:
        _verify_weight_manifest()

        import onnxruntime as ort

        # Preload the CUDA/cuDNN libs that onnxruntime-gpu installs into the
        # nvidia site packages, so CUDAExecutionProvider can dlopen them.
        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls(cuda=True, cudnn=True, directory="")

        from rembg.session_factory import new_session

        self.session = new_session(ENGINE, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])

    @modal.method()
    def process(self, data: bytes) -> dict:
        from PIL import Image, ImageOps

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


def _safe_input_path(input_path: str) -> Path:
    rel = Path(input_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("input_path must be relative to /artifacts")
    if not rel.parts or rel.parts[0] not in {"client-inputs", "source-inputs"}:
        raise ValueError("input_path must be under client-inputs/ or source-inputs/")
    return rel


def _legacy_canonical(rel: Path) -> dict[str, object]:
    path = Path(ARTIFACT_ROOT) / rel
    metadata = validate_canonical_input(path, rel.as_posix())
    data = path.read_bytes()
    sha256 = str(metadata["sha256"])
    return {
        "path": rel.as_posix(),
        "strategy": "legacy-canonical-pass-through",
        "source_sha256": sha256,
        "canonical_sha256": sha256,
        "bytes": len(data),
        "canonical_size": [1024, 1024],
        "engine": None,
    }


def _write_conditioned(payload: dict[str, object]) -> dict[str, object]:
    data = bytes(payload["canonical_bytes"])
    sha256 = str(payload["canonical_sha256"])
    rel = Path("client-inputs") / f"{sha256}.png"
    destination = Path(ARTIFACT_ROOT) / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        artifacts.commit()
    result = {key: value for key, value in payload.items() if key != "canonical_bytes"}
    result.update({"path": rel.as_posix(), "bytes": len(data)})
    return result


@app.function(
    image=conditioning_image,
    volumes={ARTIFACT_ROOT: artifacts},
    timeout=10 * 60,
)
def condition(input_path: str) -> dict[str, object]:
    """Condition a public source image into the internal canonical worker input."""
    rel = _safe_input_path(input_path)
    artifacts.reload()
    path = Path(ARTIFACT_ROOT) / rel
    if not path.is_file():
        raise FileNotFoundError(input_path)
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("source image exceeds 20 MiB")

    # Legacy callers already upload the verified canonical worker contract.
    # Preserve those bytes exactly so experiment 041 remains a strict parity gate.
    if rel.parts[0] == "client-inputs":
        return _legacy_canonical(rel)

    data = path.read_bytes()
    try:
        payload = condition_image(data)
    except BackgroundMaskRequired:
        prediction = RemBgWorker().process.remote(data)
        mask_bytes = base64.b64decode(prediction["mask_bytes_b64"])
        payload = condition_image(data, mask_bytes)
        payload["engine"] = prediction.get("engine", ENGINE)
        payload["mask_elapsed_ms"] = prediction.get("elapsed_ms")
    else:
        payload["engine"] = None
    return _write_conditioned(payload)


@app.function(image=conditioning_image, timeout=10 * 60)
@modal.asgi_app()
def web():
    from fastapi import Body, FastAPI, HTTPException

    api = FastAPI(title="modal-3D rembg", version="1")

    @api.get("/health")
    def health() -> dict:
        return {"status": "healthy", "service": APP_NAME, "engine": ENGINE}

    @api.post("/preprocess")
    async def preprocess(data: bytes = Body(...)) -> dict:
        if not data:
            raise HTTPException(status_code=400, detail="请求体不能为空")
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="图片超过 20 MiB")
        worker = RemBgWorker()
        try:
            return worker.process.remote(data)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    return api
