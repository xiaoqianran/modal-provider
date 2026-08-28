"""Dynamic HTTP and Python gateway for long-running 3D generation jobs."""

from __future__ import annotations

import time
from pathlib import Path

import modal

from .capabilities import model_capability, model_registry, validate_options_for_capability
from .gateway_registry import reconcile_registry as reconcile_worker_registry
from .gateway_routing import (
    generation_job_key,
    normalize_input_path,
    public_capabilities,
    spawn_generation,
)
from .gateway_tasks import TaskCoordinator

APP_NAME = "modal-3d-gateway"
# This value is consumed while the deployment graph is built on the desktop.
# Keep it platform-neutral; construct a concrete Path only inside Linux runtime code.
ARTIFACT_ROOT = "/artifacts"
RETENTION_SECONDS = 7 * 86400

app = modal.App(APP_NAME)
image = modal.Image.debian_slim(python_version="3.11").uv_pip_install(
    "fastapi==0.116.1",
    "pydantic==2.11.7",
)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)
tasks = modal.Dict.from_name("modal-3d-tasks", create_if_missing=True)
job_keys = modal.Dict.from_name("modal-3d-job-keys", create_if_missing=True)
registry_health = modal.Dict.from_name("modal-3d-registry-health", create_if_missing=True)
registry = model_registry()
REGISTRY_FAILURE_LIMIT = 3
CONDITIONER_APP = "modal-3d-rembg"
CONDITIONER_FUNCTION = "condition"


def _task_coordinator() -> TaskCoordinator:
    return TaskCoordinator(tasks, job_keys, retention_seconds=RETENTION_SECONDS)


def _public_capabilities() -> dict:
    return public_capabilities(registry)


def _submit(model: str, input_path: str, options: dict | None = None) -> dict:
    capability = model_capability(model, registry)
    validated = validate_options_for_capability(capability, options)
    normalized_path = normalize_input_path(input_path)
    key = generation_job_key(model, normalized_path, validated)
    coordinator = _task_coordinator()
    reservation, existing = coordinator.reserve(key, modal.functions.FunctionCall.from_id)
    if existing is not None:
        return existing
    assert reservation is not None

    try:
        if normalized_path.startswith("source-inputs/"):
            call = conditioned_generation.spawn(capability, normalized_path, validated)
        else:
            call = spawn_generation(capability, normalized_path, validated)
        record = coordinator.create_record(call, model, "generation", capability, key)
    except Exception:
        coordinator.release(key, reservation)
        raise
    coordinator.publish(key, call.object_id)
    return record


def _condition_and_generate(capability: dict, input_path: str, options: dict) -> dict:
    conditioner = modal.Function.from_name(CONDITIONER_APP, CONDITIONER_FUNCTION)
    conditioned = conditioner.remote(input_path)
    if not isinstance(conditioned, dict) or not isinstance(conditioned.get("path"), str):
        raise TypeError("modal-3D conditioner returned an invalid result")
    call = spawn_generation(capability, conditioned["path"], options)
    result = call.get(timeout=35 * 60)
    if not isinstance(result, dict):
        raise TypeError("modal-3D worker returned an invalid result")
    output = dict(result)
    output["conditioning"] = conditioned
    return output


@app.function(image=image, timeout=40 * 60, max_containers=20)
def conditioned_generation(capability: dict, input_path: str, options: dict) -> dict:
    return _condition_and_generate(capability, input_path, options)


@app.function(image=image)
def capabilities() -> dict:
    return _public_capabilities()


@app.function(image=image, max_containers=1)
@modal.concurrent(max_inputs=32, target_inputs=8)
def submit(model: str, input_path: str, options: dict | None = None) -> dict:
    return _submit(model, input_path, options)



@app.function(
    image=image,
    schedule=modal.Cron("0 3 * * *", timezone="Asia/Shanghai"),
    volumes={ARTIFACT_ROOT: artifacts},
    timeout=10 * 60,
)
def cleanup_artifacts() -> dict:
    artifact_root = Path(ARTIFACT_ROOT)
    cutoff = time.time() - RETENTION_SECONDS
    deleted_files = 0
    deleted_bytes = 0
    for path in artifact_root.rglob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            deleted_bytes += path.stat().st_size
            path.unlink()
            deleted_files += 1
    for path in sorted(
        (item for item in artifact_root.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            path.rmdir()
        except OSError:
            pass
    artifacts.commit()

    deleted_tasks = _task_coordinator().cleanup(cutoff)
    return {"files": deleted_files, "bytes": deleted_bytes, "tasks": deleted_tasks}


def _worker_health(worker_app: str) -> dict:
    return modal.Function.from_name(worker_app, "health").remote()


def _reconcile_registry() -> dict:
    return reconcile_worker_registry(
        registry,
        registry_health,
        _worker_health,
        failure_limit=REGISTRY_FAILURE_LIMIT,
    )


@app.function(
    image=image,
    schedule=modal.Cron("30 3 * * *", timezone="Asia/Shanghai"),
    timeout=10 * 60,
)
def reconcile_registry() -> dict:
    return _reconcile_registry()


@app.function(image=image)
@modal.asgi_app()
def web():
    from fastapi import FastAPI

    api = FastAPI(title="modal-3D Gateway", version="2")

    @api.get("/capabilities")
    def get_capabilities():
        return _public_capabilities()

    return api
