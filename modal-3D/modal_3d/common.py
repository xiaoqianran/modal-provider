from __future__ import annotations

import hashlib
import sys
import time
from copy import deepcopy
from pathlib import Path

import modal

from .png import alpha_range as _png_rgba_alpha_range

# Keep values captured by serialized Modal adapter functions platform-neutral.
# A concrete Path created while deploying from Windows becomes WindowsPath in
# cloudpickle and cannot be unpickled inside Modal's Linux containers.
ARTIFACT_ROOT = "/artifacts"
REGISTRY_NAME = "modal-3d-model-registry"
# Every serialized adapter deployment must carry this revision into the registry.
# Bump it whenever the closure/runtime contract changes so desktop deployment can
# distinguish a merely-existing Worker from the Worker version it actually needs.
WORKER_ADAPTER_REVISION = "modal-3d.worker-adapter.v3"
CANONICAL_INPUT = {
    "role": "canonical_rgba",
    "mime": "image/png",
    "mode": "RGBA",
    "width": 1024,
    "height": 1024,
    "bit_depth": 8,
    "layout": "letterbox",
    "alpha": "channel_required",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def validate_canonical_png(path: Path) -> dict:
    """Validate the canonical object contract before a GPU worker is started."""
    data = path.read_bytes()
    if len(data) < 33 or data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise ValueError("input must be a valid PNG with an IHDR header")
    ihdr_length = int.from_bytes(data[8:12], "big")
    if ihdr_length != 13:
        raise ValueError("PNG IHDR length must be 13")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    bit_depth = data[24]
    color_type = data[25]
    compression = data[26]
    filter_method = data[27]
    interlace = data[28]
    if (width, height) != (1024, 1024):
        raise ValueError(f"canonical input must be 1024x1024, got {width}x{height}")
    if bit_depth != 8 or color_type != 6:
        raise ValueError("canonical input must be 8-bit RGBA PNG")
    if (compression, filter_method, interlace) != (0, 0, 0):
        raise ValueError("canonical PNG must use standard compression/filtering and no interlace")
    alpha_min, alpha_max = _png_rgba_alpha_range(data, width, height)
    if alpha_max <= 8:
        raise ValueError("canonical input contains no visible foreground")
    if alpha_min == 255:
        raise ValueError("canonical input must contain transparent background pixels")
    return {
        "width": width,
        "height": height,
        "mode": "RGBA",
        "alpha_min": alpha_min,
        "alpha_max": alpha_max,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def validate_canonical_input(path: Path, input_path: str | None = None) -> dict:
    """Validate canonical PNG bytes and, for content-addressed inputs, their filename hash."""
    metadata = validate_canonical_png(path)
    candidate = Path(input_path).stem if input_path is not None else path.stem
    if len(candidate) == 64 and all(char in "0123456789abcdef" for char in candidate.lower()):
        if metadata["sha256"] != candidate.lower():
            raise ValueError("canonical input SHA256 does not match its content-addressed filename")
    return metadata


def validate_glb(path: Path, expected_size: int | None = None) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if expected_size is not None and size != expected_size:
        raise ValueError(f"GLB byte count mismatch: worker={expected_size}, volume={size}")
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] != b"glTF":
            raise ValueError("artifact must be a GLB with glTF magic")
        version = int.from_bytes(header[4:8], "little")
        declared_size = int.from_bytes(header[8:12], "little")
        if version != 2:
            raise ValueError(f"artifact must be GLB version 2, got {version}")
        if declared_size != size:
            raise ValueError(f"GLB declared length {declared_size} does not match file size {size}")
        digest = hashlib.sha256()
        digest.update(header)
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return {
        "bytes": size,
        "sha256": digest.hexdigest(),
        "mime": "model/gltf-binary",
        "glb_version": version,
    }


def worker_capability(
    model_id: str,
    name: str,
    worker_app: str,
    description: str,
    options: dict,
    *,
    warm_seconds: float,
    cold_start_seconds: float | None = None,
    generation_entrypoint: dict | None = None,
    profile: dict | None = None,
    profile_name: str = "推荐 · 已验证",
    profile_metadata: dict | None = None,
    reference_metadata: dict | None = None,
    output: str = "geometry",
    deployment: dict | None = None,
    priority: int = 1000,
) -> dict:
    reference = {"warm_seconds": warm_seconds}
    if cold_start_seconds is not None:
        reference["cold_start_seconds"] = cold_start_seconds
    if reference_metadata:
        reference.update(deepcopy(reference_metadata))

    recommended_profile = {
        "id": "recommended",
        "name": profile_name,
        "options": profile or {},
    }
    if profile_metadata:
        recommended_profile.update(deepcopy(profile_metadata))

    capability = {
        "id": model_id,
        "name": name,
        "description": description,
        "status": "enabled",
        "worker_app": worker_app,
        "output": output,
        "artifact": {"mime": "model/gltf-binary", "extension": ".glb"},
        "input": deepcopy(CANONICAL_INPUT),
        "profiles": [recommended_profile],
        "options": options,
        "priority": priority,
        "reference": reference,
    }
    if generation_entrypoint:
        capability["generation_entrypoint"] = deepcopy(generation_entrypoint)
    deployment_metadata = dict(deployment or {})
    deployment_metadata["adapter_revision"] = WORKER_ADAPTER_REVISION
    capability["deployment"] = deployment_metadata
    return capability


def generation_result(model: str, value: dict, artifact: dict) -> dict:
    timing = {key: value[key] for key in ("load_s", "inference_s") if key in value}
    reserved = {"model", "artifact", "glb_bytes", *timing}
    return {
        "model": model,
        "artifact": deepcopy(artifact),
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
    adapter_image = modal.Image.debian_slim(python_version=adapter_python).add_local_python_source(
        "modal_3d", copy=True
    )

    def generate(input_path: str, options: dict | None = None) -> dict:
        rel = Path(input_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("input_path must be relative to /artifacts")
        path = Path(ARTIFACT_ROOT) / rel
        if not path.is_file():
            artifacts_volume.reload()
        if not path.is_file():
            raise FileNotFoundError(input_path)
        validate_canonical_input(path, input_path)
        remote_cls = modal.Cls.from_name(worker_app, model_cls_name)
        value = remote_cls().generate.remote(path.read_bytes(), **dict(options or {}))
        artifact_rel = Path(str(value.get("artifact", "")))
        if not artifact_rel.parts or artifact_rel.is_absolute() or ".." in artifact_rel.parts:
            raise ValueError("worker artifact path must be relative to /artifacts")
        expected_size = value.get("glb_bytes")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size <= 0:
            raise ValueError("worker result must contain a positive glb_bytes integer")
        artifacts_volume.reload()
        artifact_path = Path(ARTIFACT_ROOT) / artifact_rel
        metadata = validate_glb(artifact_path, expected_size)
        metadata["path"] = artifact_rel.as_posix()
        return generation_result(model_id, value, metadata)

    def warmup() -> dict:
        remote_cls = modal.Cls.from_name(worker_app, model_cls_name)
        return remote_cls().warmup.remote()

    def health() -> dict:
        return {
            "ok": True,
            "model": model_id,
            "worker_app": worker_app,
            "adapter_revision": WORKER_ADAPTER_REVISION,
        }

    def register() -> dict:
        registry = modal.Dict.from_name(REGISTRY_NAME, create_if_missing=True)
        registered = deepcopy(manifest)
        registered_at = time.time()
        registered["registration"] = {
            "registered_at": registered_at,
            "worker_app": worker_app,
            "adapter_revision": WORKER_ADAPTER_REVISION,
        }
        registry.put(model_id, registered)
        return {
            "registered": model_id,
            "worker_app": worker_app,
            "registered_at": registered_at,
            "adapter_revision": WORKER_ADAPTER_REVISION,
        }

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
    app.function(
        name="health",
        image=adapter_image,
        serialized=True,
        timeout=60,
        max_containers=1,
    )(health)
    register_fn = app.function(
        name="register",
        image=adapter_image,
        serialized=True,
        timeout=60,
        max_containers=1,
    )(register)
    return generate_fn, warmup_fn, register_fn
