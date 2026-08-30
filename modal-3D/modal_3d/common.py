from __future__ import annotations

import hashlib
import time
from copy import deepcopy
from pathlib import Path

from .png import alpha_range as _png_rgba_alpha_range

# Keep deployment-time constants platform-neutral. A concrete Path created on
# Windows can be serialized into the Modal class definition and fail to unpickle
# inside Linux containers.
ARTIFACT_ROOT = "/artifacts"
ARTIFACT_VOLUME = "modal-gen-artifacts"
# Model workers consume only canonical inputs here. Shared raw sources are prepared by
# RemBgWorker before a model worker is spawned.
CLIENT_INPUT_NAMESPACE = "client-inputs"
# Historical capability field name: this is now the direct worker deployment
# revision, not a CPU adapter revision. Keep the value/field stable for v3 clients.
WORKER_ADAPTER_REVISION = "modal-3d.worker-adapter.v5"
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
    if (
        len(candidate) == 64
        and all(char in "0123456789abcdef" for char in candidate.lower())
        and metadata["sha256"] != candidate.lower()
    ):
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


def read_canonical_input(
    artifacts_volume,
    input_path: str,
    *,
    namespace: str = CLIENT_INPUT_NAMESPACE,
) -> bytes:
    """Read and validate a client-uploaded canonical input inside a GPU container."""
    rel = Path(input_path)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] != namespace:
        raise ValueError(f"input_path must be under {namespace}/ and relative to {ARTIFACT_ROOT}")
    path = Path(ARTIFACT_ROOT) / rel
    if not path.is_file():
        artifacts_volume.reload()
    if not path.is_file():
        raise FileNotFoundError(input_path)
    validate_canonical_input(path, input_path)
    return path.read_bytes()


def pinned_hf_snapshot(
    cache_dir: str | Path,
    repo_id: str,
    revision: str,
    *,
    required_files: tuple[str, ...] = (),
) -> Path:
    """Return a pinned HF snapshot path and fail if required files are missing.

    Runtime code should consume this local path directly instead of resolving a
    repo id through Hugging Face cache refs. This keeps GPU startup deterministic
    under HF_HUB_OFFLINE and independent of refs/main/cache-version behavior.
    """
    if not repo_id or "/" not in repo_id:
        raise ValueError("repo_id must be an owner/name Hugging Face id")
    forbidden = ("\\", "/", "\n", "\r")
    if not revision or any(ch in revision for ch in forbidden):
        raise ValueError("revision must be a simple cache revision")

    snapshot = Path(cache_dir) / f"models--{repo_id.replace('/', '--')}" / "snapshots" / revision
    if not snapshot.is_dir():
        raise FileNotFoundError(f"Hugging Face snapshot missing: {snapshot}")
    missing = [name for name in required_files if not (snapshot / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Hugging Face snapshot {repo_id}@{revision} is incomplete: {missing}"
        )
    return snapshot


def run_generation_job(
    model_id: str,
    artifacts_volume,
    generate_image,
    input_path: str,
    options: dict | None = None,
    *,
    namespace: str = CLIENT_INPUT_NAMESPACE,
) -> dict:
    """Run one GPU generation job end to end inside the model container.

    Every worker exposes this same body as `Model.generate_job` so the local
    client can spawn the GPU class method directly. Doing the input/artifact
    validation here (instead of in a CPU adapter function) removes one Modal
    container cold start from every submission.
    """
    job_t0 = time.perf_counter()

    input_t0 = time.perf_counter()
    image_bytes = read_canonical_input(artifacts_volume, input_path, namespace=namespace)
    input_validation_s = time.perf_counter() - input_t0

    value = generate_image(image_bytes, **dict(options or {}))
    if not isinstance(value, dict):
        raise TypeError("worker generation must return an object")

    artifact_rel = Path(str(value.get("artifact", "")))
    if not artifact_rel.parts or artifact_rel.is_absolute() or ".." in artifact_rel.parts:
        raise ValueError("worker artifact path must be relative to /artifacts")
    expected_size = value.get("glb_bytes")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size <= 0:
        raise ValueError("worker result must contain a positive glb_bytes integer")

    artifact_t0 = time.perf_counter()
    metadata = validate_glb(Path(ARTIFACT_ROOT) / artifact_rel, expected_size)
    artifact_validation_s = time.perf_counter() - artifact_t0
    metadata["path"] = artifact_rel.as_posix()

    timings = value.setdefault("timings", {})
    timings["job_input_validation_s"] = input_validation_s
    timings["job_artifact_validation_s"] = artifact_validation_s
    timings["job_total_s"] = time.perf_counter() - job_t0
    return generation_result(model_id, value, metadata)
