"""Thin CPU API. No model weights and no GPU allocation here."""

import modal
from fastapi import HTTPException
from pydantic import BaseModel, Field

from .common import ModelName

app = modal.App("modal-3d-gateway")
web_image = modal.Image.debian_slim(python_version="3.11").uv_pip_install("fastapi", "pydantic")

WORKERS = {
    ModelName.HUNYUAN21_PP: ("modal-3d-hunyuan", "generate"),
    ModelName.FASTSAM3D_PP: ("modal-3d-fastsam3d", "generate"),
    ModelName.TRELLIS2_PP: ("modal-3d-trellis2", "Model.generate"),
}


class Submit(BaseModel):
    model: ModelName
    input_path: str
    options: dict = Field(default_factory=dict)


@app.function(image=web_image)
@modal.fastapi_endpoint(method="POST")
def submit(req: Submit):
    app_name, function_name = WORKERS[req.model]
    fn = modal.Function.from_name(app_name, function_name)
    call = fn.spawn(req.input_path, req.options)
    return {"call_id": call.object_id, "model": req.model}


@app.function(image=web_image)
@modal.fastapi_endpoint(method="GET")
def result(call_id: str):
    try:
        call = modal.FunctionCall.from_id(call_id)
        value = call.get(timeout=0)
        return {"status": "done", "result": value}
    except TimeoutError:
        return {"status": "pending"}
    except modal.exception.OutputExpiredError:
        raise HTTPException(status_code=410, detail="result expired")
