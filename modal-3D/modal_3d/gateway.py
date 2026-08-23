"""Private CPU router for long-running 3D generation jobs."""

import modal

from .common import ModelName

app = modal.App("modal-3d-gateway")
image = modal.Image.debian_slim(python_version="3.11")

WORKERS = {
    ModelName.HUNYUAN21_PP: "modal-3d-hunyuan",
    ModelName.FASTSAM3D_PP: "modal-3d-fastsam3d",
    ModelName.TRELLIS2_PP: "modal-3d-hermit-trellis2-plus-plus",
    ModelName.PIXAL3D: "modal-3d-pixal3d",
}


@app.function(image=image)
def submit(model: str, input_path: str, options: dict | None = None) -> dict:
    model_name = ModelName(model)
    fn = modal.Function.from_name(WORKERS[model_name], "generate")
    call = fn.spawn(input_path, dict(options or {}))
    return {"call_id": call.object_id, "model": model_name.value}
