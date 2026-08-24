from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import modal

ARTIFACT_ROOT = Path("/artifacts")
REGISTRY_NAME = "modal-3d-model-registry"


def worker_capability(
    model_id: str,
    name: str,
    worker_app: str,
    description: str,
    options: dict,
    *,
    warm_seconds: float,
    profile: dict | None = None,
    output: str = "geometry",
    deployment: dict | None = None,
    priority: int = 1000,
) -> dict:
    capability = {
        "id": model_id,
        "name": name,
        "description": description,
        "status": "enabled",
        "worker_app": worker_app,
        "output": output,
        "artifact": {"mime": "model/gltf-binary", "extension": ".glb"},
        "input": {"role": "canonical_rgba", "mime": "image/png", "alpha": "required"},
        "profiles": [{"id": "recommended", "name": "推荐 · 已验证", "options": profile or {}}],
        "options": options,
        "priority": priority,
        "reference": {"warm_seconds": warm_seconds},
    }
    if deployment:
        capability["deployment"] = deployment
    return capability


def generation_result(model: str, value: dict) -> dict:
    path = value.get("artifact")
    size = value.get("glb_bytes")
    if not path or size is None:
        raise ValueError("worker result must contain artifact and glb_bytes")

    timing = {key: value[key] for key in ("load_s", "inference_s") if key in value}
    reserved = {"model", "artifact", "glb_bytes", *timing}
    return {
        "model": model,
        "artifact": {"path": path, "bytes": size, "mime": "model/gltf-binary"},
        "timing": timing,
        "metrics": {key: val for key, val in value.items() if key not in reserved},
    }


def register_worker_entrypoint(
    app: modal.App,
    artifacts_volume: modal.Volume,
    model_cls,
    capability: dict,
    *,
    python_version: str = "3.11",
):
    """Attach the standard generate, warmup and registry functions to a worker app."""
    from .capabilities import validate_capability

    manifest = validate_capability(capability)
    model_id = manifest["id"]
    worker_app = manifest["worker_app"]
    model_cls_name = model_cls.__name__
    # serialized=True requires the adapter runtime to match the Python version
    # that serialized the closure; it is independent from the GPU worker Python.
    adapter_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    adapter_image = modal.Image.debian_slim(python_version=adapter_python)

    def generate(input_path: str, options: dict | None = None) -> dict:
        rel = Path(input_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("input_path must be relative to /artifacts")
        path = ARTIFACT_ROOT / rel
        if not path.is_file():
            artifacts_volume.reload()
        if not path.is_file():
            raise FileNotFoundError(input_path)
        remote_cls = modal.Cls.from_name(worker_app, model_cls_name)
        value = remote_cls().generate.remote(path.read_bytes(), **dict(options or {}))
        return generation_result(model_id, value)

    def warmup() -> dict:
        remote_cls = modal.Cls.from_name(worker_app, model_cls_name)
        return remote_cls().warmup.remote()

    def register() -> dict:
        registry = modal.Dict.from_name(REGISTRY_NAME, create_if_missing=True)
        registry.put(model_id, deepcopy(manifest))
        return {"registered": model_id, "worker_app": manifest["worker_app"]}

    function_options = {
        "image": adapter_image,
        "serialized": True,
        "timeout": 30 * 60,
        "max_containers": 1,
    }
    generate_fn = app.function(
        name="generate",
        volumes={str(ARTIFACT_ROOT): artifacts_volume},
        **function_options,
    )(generate)
    warmup_fn = app.function(name="warmup", **function_options)(warmup)
    register_fn = app.function(
        name="register",
        image=adapter_image,
        serialized=True,
        timeout=60,
        max_containers=1,
    )(register)
    return generate_fn, warmup_fn, register_fn
