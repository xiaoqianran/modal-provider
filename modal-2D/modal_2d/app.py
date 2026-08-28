import os
from pathlib import Path
from time import perf_counter

import modal

from .artifacts import artifact_path, write_png
from .contracts import (
    APP_NAME,
    capabilities_document,
    model_spec,
    normalize_batch_request,
    normalize_request,
)
from .runtime import generate_png, load_pipeline, model_snapshot_ready

MODEL_ROOT = Path("/models")
ARTIFACT_ROOT = Path("/artifacts")
MODELS_VOLUME = "modal-2d-models"
ARTIFACTS_VOLUME = "modal-2d-artifacts"

app = modal.App(APP_NAME)
models = modal.Volume.from_name(MODELS_VOLUME, create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACTS_VOLUME, create_if_missing=True)

# SANA-Sprint checkpoints are public. A Hugging Face secret is optional and is
# only attached when the deployer explicitly opts in with this environment variable.
# Example: MODAL_2D_HF_SECRET=huggingface modal deploy modal_2d/app.py
HUGGINGFACE_SECRET_NAME = os.environ.get("MODAL_2D_HF_SECRET", "").strip()
PREFETCH_SECRETS = (
    [modal.Secret.from_name(HUGGINGFACE_SECRET_NAME)] if HUGGINGFACE_SECRET_NAME else []
)

control_image = modal.Image.debian_slim(python_version="3.12").add_local_python_source("modal_2d")
download_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("huggingface-hub>=0.30,<2", "hf_xet")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
    .add_local_python_source("modal_2d")
)
inference_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "accelerate>=1.2,<2",
        "diffusers>=0.33,<1",
        "pillow>=11,<13",
        "safetensors>=0.5,<1",
        "sentencepiece>=0.2,<1",
        "torch>=2.5,<3",
        "torchvision>=0.20,<1",
        "transformers>=4.46,<5",
    )
    .add_local_python_source("modal_2d")
)


@app.function(image=control_image)
def capabilities() -> dict[str, object]:
    return capabilities_document()


@app.function(
    image=download_image,
    volumes={str(MODEL_ROOT): models},
    secrets=PREFETCH_SECRETS,
    timeout=30 * 60,
)
def prefetch(model_id: str) -> dict[str, object]:
    from huggingface_hub import snapshot_download

    spec = model_spec(model_id)
    destination = MODEL_ROOT / spec.id
    if model_snapshot_ready(destination):
        return {"model": spec.id, "status": "cached"}
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=spec.hf_id,
        local_dir=destination,
        token=os.environ.get("HF_TOKEN") or None,
    )
    (destination / ".complete").write_text(spec.hf_id, encoding="utf-8")
    models.commit()
    return {"model": spec.id, "status": "downloaded"}


@app.cls(
    image=inference_image,
    gpu="L40S",
    timeout=15 * 60,
    scaledown_window=300,
    retries=modal.Retries(max_retries=2, backoff_coefficient=2.0),
    volumes={str(MODEL_ROOT): models, str(ARTIFACT_ROOT): artifacts},
)
class SanaSprintWorker:
    model_id: str = modal.parameter(default="sana-sprint-1.6b")

    @modal.enter()
    def load(self) -> None:
        started = perf_counter()
        models.reload()
        self.pipe = load_pipeline(self.model_id, MODEL_ROOT)
        self.worker_load_ms = round((perf_counter() - started) * 1000, 3)
        self.batch_calls = 0

    @modal.method()
    def generate(self, payload: dict[str, object]) -> dict[str, object]:
        request = normalize_request(payload)
        if request["model"] != self.model_id:
            raise ValueError("worker model does not match request model")
        data = generate_png(self.pipe, request)
        descriptor = write_png(ARTIFACT_ROOT, data)
        artifacts.commit()
        return {"model": self.model_id, "artifact": descriptor}

    @modal.method()
    def generate_batch(self, payload: dict[str, object]) -> dict[str, object]:
        batch = normalize_batch_request(payload)
        if batch["model"] != self.model_id:
            raise ValueError("worker model does not match request model")
        requests = batch["requests"]
        batch_started = perf_counter()
        worker_reused = self.batch_calls > 0
        descriptors: list[dict[str, object]] = []
        item_timings: list[dict[str, object]] = []
        for request in requests:
            item_started = perf_counter()
            inference_started = perf_counter()
            data = generate_png(self.pipe, request)
            inference_ms = round((perf_counter() - inference_started) * 1000, 3)
            write_started = perf_counter()
            descriptor = write_png(ARTIFACT_ROOT, data)
            write_ms = round((perf_counter() - write_started) * 1000, 3)
            descriptors.append(descriptor)
            item_timings.append({
                "seed": request["seed"],
                "inference_ms": inference_ms,
                "artifact_write_ms": write_ms,
                "total_ms": round((perf_counter() - item_started) * 1000, 3),
            })
        artifacts.commit()
        self.batch_calls += 1
        return {
            "model": self.model_id,
            "artifacts": descriptors,
            "timing": {
                "worker_reused": worker_reused,
                "worker_load_ms": None if worker_reused else getattr(self, "worker_load_ms", None),
                "batch_total_ms": round((perf_counter() - batch_started) * 1000, 3),
                "items": item_timings,
            },
        }


@app.function(image=control_image, volumes={str(ARTIFACT_ROOT): artifacts}, timeout=5 * 60)
def read_artifact(artifact_id: str) -> bytes:
    artifacts.reload()
    path = artifact_path(ARTIFACT_ROOT, artifact_id)
    if not path.is_file():
        raise FileNotFoundError(artifact_id)
    return path.read_bytes()
