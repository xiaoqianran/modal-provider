import os
from pathlib import Path

import modal

from .artifacts import artifact_path
from .capabilities import capabilities_document
from .constants import APP_NAME, ARTIFACT_VOLUME, MODELS_VOLUME
from .models import model_spec
from .runtime import model_snapshot_ready

MODEL_ROOT = Path("/models")
ARTIFACT_ROOT = Path("/artifacts")

app = modal.App(APP_NAME)
models = modal.Volume.from_name(MODELS_VOLUME, create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)

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


@app.function(image=control_image)
def capabilities() -> dict[str, object]:
    return capabilities_document()


@app.function(
    image=download_image,
    volumes={str(MODEL_ROOT): models},
    secrets=PREFETCH_SECRETS,
    timeout=45 * 60,
)
def prefetch(model_id: str) -> dict[str, object]:
    from huggingface_hub import snapshot_download

    spec = model_spec(model_id)
    destination = MODEL_ROOT / spec.id
    if model_snapshot_ready(destination, spec.snapshot_file):
        return {"model": spec.id, "status": "cached", "revision": spec.revision}
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=spec.hf_id,
        revision=spec.revision,
        local_dir=destination,
        token=os.environ.get("HF_TOKEN") or None,
    )
    (destination / ".complete").write_text(
        f"{spec.hf_id}@{spec.revision}",
        encoding="utf-8",
    )
    models.commit()
    return {"model": spec.id, "status": "downloaded", "revision": spec.revision}


@app.function(image=control_image, volumes={str(ARTIFACT_ROOT): artifacts}, timeout=5 * 60)
def read_artifact(artifact_id: str) -> bytes:
    artifacts.reload()
    path = artifact_path(ARTIFACT_ROOT, artifact_id)
    if not path.is_file():
        raise FileNotFoundError(artifact_id)
    return path.read_bytes()
