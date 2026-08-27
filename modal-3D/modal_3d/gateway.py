"""Dynamic HTTP and Python gateway for long-running 3D generation jobs."""

from __future__ import annotations

import hashlib
import json
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


def _public_capabilities() -> dict:
    document = capabilities_document(registry)
    for model in document.get("models", []):
        if isinstance(model, dict):
            model.pop("generation_entrypoint", None)
    return document


def _job_key(model: str, input_path: str, options: dict) -> str:
    payload = json.dumps(
        {"model": model, "input_path": input_path, "options": options},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_input_path(input_path: str) -> str:
    rel = Path(input_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("input_path must be relative to /artifacts")
    if not rel.parts or rel.parts[0] != "client-inputs":
        raise ValueError("input_path must be under client-inputs/")
    return rel.as_posix()


def _task_record(call, model: str, kind: str, capability: dict, job_key: str) -> dict:
    record = {
        "task_id": call.object_id,
        "call_id": call.object_id,
        "job_key": job_key,
        "model": model,
        "kind": kind,
        "status": "running",
        "submitted_at": time.time(),
        # Cold-start and warm latency are different metrics. Never use the
        # warm request latency as a proxy for container/model startup.
        "cold_start_seconds": capability.get("reference", {}).get("cold_start_seconds"),
        "deduplicated": False,
    }
    tasks.put(call.object_id, record)
    job_keys.put(job_key, call.object_id)
    return record


def _reusable_task(job_key: str) -> dict | None:
    task_id = job_keys.get(job_key)
    if not task_id:
        return None
    record = tasks.get(task_id)
    if not record:
        job_keys.pop(job_key, None)
        return None
    age = time.time() - record.get("submitted_at", 0)
    if age > RETENTION_SECONDS:
        job_keys.pop(job_key, None)
        return None

    # Task records are intentionally lightweight and the desktop client polls the
    # underlying FunctionCall directly. On a duplicate submit, refresh the remote
    # call once so only genuinely in-flight work is deduplicated.
    call = modal.functions.FunctionCall.from_id(task_id)
    try:
        result = call.get(timeout=0)
    except TimeoutError:
        reused = dict(record)
        reused["deduplicated"] = True
        return reused
    except Exception as exc:  # noqa: BLE001 - terminal remote failure permits a retry.
        record.update(
            {
                "status": "failed",
                "finished_at": time.time(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
        tasks.put(task_id, record)
        job_keys.pop(job_key, None)
        return None
    else:
        record.update({"status": "completed", "finished_at": time.time(), "result": result})
        tasks.put(task_id, record)
        job_keys.pop(job_key, None)
        return None


def _spawn_generation(capability: dict, input_path: str, options: dict):
    entrypoint = capability.get("generation_entrypoint")
    if entrypoint is not None:
        remote_cls = modal.Cls.from_name(capability["worker_app"], entrypoint["class_name"])
        method = getattr(remote_cls(), entrypoint["method_name"])
        return method.spawn(input_path, options)
    fn = modal.Function.from_name(capability["worker_app"], "generate")
    return fn.spawn(input_path, options)


def _submit(model: str, input_path: str, options: dict | None = None) -> dict:
    capability = model_capability(model, registry)
    validated = validate_options(model, options, registry)
    normalized_path = _validate_input_path(input_path)
    key = _job_key(model, normalized_path, validated)
    existing = _reusable_task(key)
    if existing is not None:
        return existing
    call = _spawn_generation(capability, normalized_path, validated)
    return _task_record(call, model, "generation", capability, key)


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
    return _public_capabilities()


@app.function(image=image, max_containers=1)
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

    deleted_tasks = 0
    for task_id, record in tasks.items():
        if record.get("submitted_at", time.time()) < cutoff:
            tasks.pop(task_id, None)
            if record.get("job_key"):
                job_keys.pop(record["job_key"], None)
            deleted_tasks += 1
    for key, task_id in list(job_keys.items()):
        if tasks.get(task_id) is None:
            job_keys.pop(key, None)
    return {"files": deleted_files, "bytes": deleted_bytes, "tasks": deleted_tasks}


def _reconcile_registry() -> dict:
    checked = 0
    healthy = 0
    removed: list[str] = []
    failures: dict[str, int] = {}
    for model_id, capability in list(registry.items()):
        checked += 1
        worker_app = str(capability.get("worker_app", ""))
        try:
            probe = modal.Function.from_name(worker_app, "health").remote()
            if not isinstance(probe, dict) or probe.get("ok") is not True or probe.get("model") != model_id:
                raise RuntimeError("worker health payload does not match registry entry")
        except Exception as exc:  # noqa: BLE001 - health failures are recorded, not surfaced.
            previous = registry_health.get(model_id, {}) or {}
            count = int(previous.get("consecutive_failures", 0)) + 1
            failures[model_id] = count
            registry_health.put(
                model_id,
                {
                    "consecutive_failures": count,
                    "last_failure_at": time.time(),
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
            )
            if count >= REGISTRY_FAILURE_LIMIT:
                registry.pop(model_id, None)
                registry_health.pop(model_id, None)
                removed.append(model_id)
        else:
            healthy += 1
            registry_health.put(
                model_id,
                {
                    "consecutive_failures": 0,
                    "last_success_at": time.time(),
                },
            )
    return {"checked": checked, "healthy": healthy, "removed": removed, "failures": failures}


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
