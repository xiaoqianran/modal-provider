"""Dynamic HTTP and Python gateway for long-running 3D generation jobs."""

from __future__ import annotations

import base64
import binascii
import time
from pathlib import Path

import modal

from .capabilities import (
    capabilities_document,
    model_capability,
    model_registry,
    validate_options,
)

APP_NAME = "modal-3d-gateway"
SAM_APP = "modal-3d-sam31"
ARTIFACT_ROOT = Path("/artifacts")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
RETENTION_SECONDS = 7 * 86400

app = modal.App(APP_NAME)
image = modal.Image.debian_slim(python_version="3.11").uv_pip_install(
    "fastapi==0.116.1",
    "pydantic==2.11.7",
)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)
tasks = modal.Dict.from_name("modal-3d-tasks", create_if_missing=True)
registry = model_registry()


def _task_record(call, model: str, kind: str, capability: dict) -> dict:
    record = {
        "task_id": call.object_id,
        "call_id": call.object_id,
        "model": model,
        "kind": kind,
        "status": "running",
        "submitted_at": time.time(),
        "cold_start_seconds": capability.get("reference", {}).get("warm_seconds"),
    }
    tasks.put(call.object_id, record)
    return record


def _submit(model: str, input_path: str, options: dict | None = None) -> dict:
    capability = model_capability(model, registry)
    validated = validate_options(model, options, registry)
    fn = modal.Function.from_name(capability["worker_app"], "generate")
    call = fn.spawn(input_path, validated)
    return _task_record(call, model, "generation", capability)


def _submit_pipeline(
    image_bytes: bytes,
    concept: str,
    model: str,
    options: dict | None = None,
) -> dict:
    capability = model_capability(model, registry)
    validated = validate_options(model, options, registry)
    fn = modal.Function.from_name(APP_NAME, "generate_from_raw")
    call = fn.spawn(image_bytes, concept, model, validated)
    return _task_record(call, model, "pipeline", capability)


def _status(task_id: str) -> dict:
    record = tasks.get(task_id)
    if record is None:
        raise KeyError(task_id)
    if record["status"] != "running":
        return record

    call = modal.functions.FunctionCall.from_id(task_id)
    try:
        result = call.get(timeout=0)
    except TimeoutError:
        elapsed = time.time() - record["submitted_at"]
        cold_start = record.get("cold_start_seconds")
        record["phase"] = (
            "cold_start_or_queued" if cold_start and elapsed < cold_start else "inference"
        )
        return record
    except Exception as exc:  # noqa: BLE001 - the remote exception is the task result.
        record.update(
            {
                "status": "failed",
                "finished_at": time.time(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
    else:
        record.update({"status": "completed", "finished_at": time.time(), "result": result})
    tasks.put(task_id, record)
    return record


@app.function(image=image)
def capabilities() -> dict:
    return capabilities_document(registry)


@app.function(image=image)
def submit(model: str, input_path: str, options: dict | None = None) -> dict:
    return _submit(model, input_path, options)


@app.function(image=image, timeout=45 * 60)
def generate_from_raw(
    image_bytes: bytes,
    concept: str,
    model: str,
    options: dict | None = None,
) -> dict:
    """Segment Top-1, materialize canonical RGBA, then run the selected 3D worker."""
    capability = model_capability(model, registry)
    validated = validate_options(model, options, registry)

    # GPU loading overlaps SAM segmentation; this is a real no-input lifecycle call,
    # not a fake inference request that can pollute worker queues or artifacts.
    modal.Function.from_name(capability["worker_app"], "warmup").spawn()

    sam = modal.Cls.from_name(SAM_APP, "Model")()
    selection = sam.segment.remote(image_bytes, concept, max_candidates=1)
    candidates = selection.get("candidates", [])
    if not candidates:
        raise ValueError(f"SAM 3.1 found no object matching: {concept}")

    candidate = candidates[0]
    materialize = modal.Function.from_name(SAM_APP, "materialize")
    canonical = materialize.remote(
        selection["scene_id"],
        selection["selection_id"],
        candidate["candidate_id"],
    )
    worker = modal.Function.from_name(capability["worker_app"], "generate")
    generation = worker.remote(canonical["canonical_path"], validated)
    return {
        "model": model,
        "selection": {
            "scene_id": selection["scene_id"],
            "selection_id": selection["selection_id"],
            "candidate": candidate,
        },
        "canonical": canonical,
        "generation": generation,
    }


@app.function(
    image=image,
    schedule=modal.Cron("0 3 * * *", timezone="Asia/Shanghai"),
    volumes={str(ARTIFACT_ROOT): artifacts},
    timeout=10 * 60,
)
def cleanup_artifacts() -> dict:
    cutoff = time.time() - RETENTION_SECONDS
    deleted_files = 0
    deleted_bytes = 0
    for path in ARTIFACT_ROOT.rglob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            deleted_bytes += path.stat().st_size
            path.unlink()
            deleted_files += 1
    for path in sorted(
        (item for item in ARTIFACT_ROOT.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            path.rmdir()
        except OSError:
            pass
    artifacts.commit()

    deleted_tasks = 0
    for task_id, record in tasks.items():
        if record.get("submitted_at", time.time()) < cutoff:
            tasks.pop(task_id, None)
            deleted_tasks += 1
    return {"files": deleted_files, "bytes": deleted_bytes, "tasks": deleted_tasks}


@app.function(image=image, volumes={str(ARTIFACT_ROOT): artifacts}, timeout=30 * 60)
@modal.asgi_app()
def web():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse

    api = FastAPI(title="modal-3D Gateway", version="2")

    def payload_string(payload: dict, key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(422, f"{key} must be a non-empty string")
        return value.strip()

    @api.get("/capabilities")
    def get_capabilities():
        return capabilities_document(registry)

    @api.post("/tasks", status_code=202)
    def post_task(payload: dict):
        try:
            return _submit(
                payload_string(payload, "model"),
                payload_string(payload, "input_path"),
                payload.get("options"),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.post("/pipelines", status_code=202)
    def post_pipeline(payload: dict):
        encoded = payload_string(payload, "image_base64")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "image_base64 is invalid") from exc
        if not image_bytes or len(image_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"image must be between 1 and {MAX_UPLOAD_BYTES} bytes")
        try:
            return _submit_pipeline(
                image_bytes,
                payload_string(payload, "concept"),
                payload_string(payload, "model"),
                payload.get("options"),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.get("/tasks/{task_id}")
    def get_task(task_id: str):
        try:
            return _status(task_id)
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc

    @api.get("/artifacts/{artifact_path:path}")
    def get_artifact(artifact_path: str):
        rel = Path(artifact_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise HTTPException(400, "artifact path must be relative")
        path = ARTIFACT_ROOT / rel
        if not path.is_file():
            artifacts.reload()
        if not path.is_file():
            raise HTTPException(404, "artifact not found")
        return FileResponse(path, media_type="model/gltf-binary", filename=path.name)

    return api
