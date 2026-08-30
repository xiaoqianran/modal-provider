import os
from pathlib import Path

import modal

from .constants import MODELS_VOLUME, PREFETCH_APP_NAME
from .models import model_spec
from .runtime import model_snapshot_ready

MODEL_ROOT = Path("/models")
APP_NAME = PREFETCH_APP_NAME
app = modal.App(APP_NAME)
models = modal.Volume.from_name(MODELS_VOLUME, create_if_missing=True)

HUGGINGFACE_SECRET_NAME = os.environ.get("MODAL_2D_HF_SECRET", "").strip()
PREFETCH_SECRETS = (
    [modal.Secret.from_name(HUGGINGFACE_SECRET_NAME)] if HUGGINGFACE_SECRET_NAME else []
)

download_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("huggingface-hub>=0.30,<2", "hf_xet")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
    .add_local_python_source("modal_2d")
)


@app.function(
    image=download_image,
    volumes={str(MODEL_ROOT): models},
    secrets=PREFETCH_SECRETS,
    timeout=45 * 60,
)
def prefetch(model_id: str) -> dict[str, object]:
    """Optional cloud-side model prefetch utility; never used as a generation gateway."""
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
