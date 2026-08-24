"""Private CPU router for long-running 3D generation jobs."""

import modal

from .capabilities import capabilities_document, validate_options, worker_app
from .common import ModelName

app = modal.App("modal-3d-gateway")
image = modal.Image.debian_slim(python_version="3.11")

@app.function(image=image)
def capabilities() -> dict:
    return capabilities_document()


@app.function(image=image)
def submit(model: str, input_path: str, options: dict | None = None) -> dict:
    model_name = ModelName(model)
    validated = validate_options(model_name, options)
    fn = modal.Function.from_name(worker_app(model_name), "generate")
    call = fn.spawn(input_path, validated)
    return {"call_id": call.object_id, "model": model_name.value}
