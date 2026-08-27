from __future__ import annotations

import binascii
import hashlib
import sys
import time
import zlib
from copy import deepcopy
from pathlib import Path

import modal

ARTIFACT_ROOT = Path("/artifacts")
REGISTRY_NAME = "modal-3d-model-registry"
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


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_upper_left = abs(estimate - upper_left)
    if distance_left <= distance_up and distance_left <= distance_upper_left:
        return left
    if distance_up <= distance_upper_left:
        return up
    return upper_left


def _png_rgba_alpha_range(data: bytes, width: int, height: int) -> tuple[int, int]:
    offset = 8
    idat = bytearray()
    saw_iend = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        body_start = offset + 8
        body_end = body_start + length
        crc_end = body_end + 4
        if crc_end > len(data):
            raise ValueError("PNG chunk is truncated")
        body = data[body_start:body_end]
        expected_crc = int.from_bytes(data[body_end:crc_end], "big")
        actual_crc = binascii.crc32(chunk_type)
        actual_crc = binascii.crc32(body, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("PNG chunk CRC is invalid")
        if chunk_type == b"IDAT":
            idat.extend(body)
        elif chunk_type == b"IEND":
            saw_iend = True
            break
        offset = crc_end
    if not idat or not saw_iend:
        raise ValueError("PNG must contain IDAT and IEND chunks")

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise ValueError("PNG image data could not be decompressed") from exc

    stride = width * 4
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise ValueError("PNG decoded data length does not match dimensions")

    # PNG filters operate independently on each byte position. For object-contract
    # validation we only need the A byte of every RGBA pixel, so reconstructing RGB
    # would add ~3x CPU work without adding any validation value.
    previous = bytearray(width)
    alpha_min = 255
    alpha_max = 0
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        row = raw[cursor : cursor + stride]
        cursor += stride
        encoded = row[3::4]
        if filter_type == 0:
            current = bytearray(encoded)
        elif filter_type in {1, 2, 3, 4}:
            current = bytearray(width)
            for index, value in enumerate(encoded):
                left = current[index - 1] if index else 0
                up = previous[index]
                upper_left = previous[index - 1] if index else 0
                if filter_type == 1:
                    predictor = left
                elif filter_type == 2:
                    predictor = up
                elif filter_type == 3:
                    predictor = (left + up) // 2
                else:
                    predictor = _paeth(left, up, upper_left)
                current[index] = (value + predictor) & 0xFF
        else:
            raise ValueError(f"unsupported PNG filter type: {filter_type}")
        alpha_min = min(alpha_min, min(current))
        alpha_max = max(alpha_max, max(current))
        previous = current
    return alpha_min, alpha_max


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
    }


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
    profile: dict | None = None,
    output: str = "geometry",
    deployment: dict | None = None,
    priority: int = 1000,
) -> dict:
    reference = {"warm_seconds": warm_seconds}
    if cold_start_seconds is not None:
        reference["cold_start_seconds"] = cold_start_seconds

    capability = {
        "id": model_id,
        "name": name,
        "description": description,
        "status": "enabled",
        "worker_app": worker_app,
        "output": output,
        "artifact": {"mime": "model/gltf-binary", "extension": ".glb"},
        "input": deepcopy(CANONICAL_INPUT),
        "profiles": [{"id": "recommended", "name": "推荐 · 已验证", "options": profile or {}}],
        "options": options,
        "priority": priority,
        "reference": reference,
    }
    if deployment:
        capability["deployment"] = deployment
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
        path = ARTIFACT_ROOT / rel
        if not path.is_file():
            artifacts_volume.reload()
        if not path.is_file():
            raise FileNotFoundError(input_path)
        validate_canonical_png(path)
        remote_cls = modal.Cls.from_name(worker_app, model_cls_name)
        value = remote_cls().generate.remote(path.read_bytes(), **dict(options or {}))
        artifact_rel = Path(str(value.get("artifact", "")))
        if not artifact_rel.parts or artifact_rel.is_absolute() or ".." in artifact_rel.parts:
            raise ValueError("worker artifact path must be relative to /artifacts")
        expected_size = value.get("glb_bytes")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size <= 0:
            raise ValueError("worker result must contain a positive glb_bytes integer")
        artifacts_volume.reload()
        artifact_path = ARTIFACT_ROOT / artifact_rel
        metadata = validate_glb(artifact_path, expected_size)
        metadata["path"] = artifact_rel.as_posix()
        return generation_result(model_id, value, metadata)

    def warmup() -> dict:
        remote_cls = modal.Cls.from_name(worker_app, model_cls_name)
        return remote_cls().warmup.remote()

    def health() -> dict:
        return {"ok": True, "model": model_id, "worker_app": worker_app}

    def register() -> dict:
        registry = modal.Dict.from_name(REGISTRY_NAME, create_if_missing=True)
        registered = deepcopy(manifest)
        registered_at = time.time()
        registered["registration"] = {
            "registered_at": registered_at,
            "worker_app": worker_app,
        }
        registry.put(model_id, registered)
        return {
            "registered": model_id,
            "worker_app": worker_app,
            "registered_at": registered_at,
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
