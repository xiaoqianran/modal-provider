from __future__ import annotations

import hashlib
import io
import json
import time
from copy import deepcopy
from pathlib import Path

from .png import alpha_range as _png_rgba_alpha_range
from .png import validate_rgba8_payload as _validate_png_rgba8_payload

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
WORKER_ADAPTER_REVISION = "modal-3d.worker-adapter.v8"
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


def _validate_canonical_png_header(data: bytes) -> dict:
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
    return {"width": width, "height": height, "mode": "RGBA"}


def validate_canonical_png_bytes(data: bytes) -> dict:
    """Fully validate canonical PNG bytes before they are uploaded for GPU use."""
    header = _validate_canonical_png_header(data)
    width = int(header["width"])
    height = int(header["height"])
    # Preserve the previous CRC/zlib integrity checks without reconstructing
    # scanlines in Python. Production workers then use Pillow's native decoder
    # for the alpha extrema; the dependency-free scanner remains the fallback.
    _validate_png_rgba8_payload(data, width, height)
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.mode != "RGBA" or image.size != (width, height):
                raise ValueError("canonical input must decode as 8-bit RGBA")
            alpha_min, alpha_max = image.getchannel("A").getextrema()
    except ImportError:
        alpha_min, alpha_max = _png_rgba_alpha_range(data, width, height)
    if alpha_max <= 8:
        raise ValueError("canonical input contains no visible foreground")
    if alpha_min == 255:
        raise ValueError("canonical input must contain transparent background pixels")
    return {
        **header,
        "alpha_min": alpha_min,
        "alpha_max": alpha_max,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def validate_canonical_png(path: Path) -> dict:
    """Fully validate a canonical PNG file."""
    return validate_canonical_png_bytes(path.read_bytes())


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


def validate_canonical_integrity_bytes(data: bytes, input_path: str) -> dict:
    """Cheap GPU-side integrity check for client-prepared canonical bytes.

    Content-addressed inputs were fully validated before upload. Inside an
    expensive GPU worker we only re-check the fixed PNG header, SHA-256 path
    binding, and alpha semantics. Non-content-addressed paths fall back to the
    full validation path rather than weakening the contract.
    """
    candidate = Path(input_path).stem
    content_addressed = len(candidate) == 64 and all(
        char in "0123456789abcdef" for char in candidate.lower()
    )
    if not content_addressed:
        return validate_canonical_png_bytes(data)

    metadata = _validate_canonical_png_header(data)
    digest = hashlib.sha256(data).hexdigest()
    if digest != candidate.lower():
        raise ValueError("canonical input SHA256 does not match its content-addressed filename")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.load()
            alpha_min, alpha_max = image.getchannel("A").getextrema()
    except ImportError:
        # Environments without Pillow keep the old fail-closed full validator.
        return validate_canonical_png_bytes(data)
    if alpha_max <= 8:
        raise ValueError("canonical input contains no visible foreground")
    if alpha_min == 255:
        raise ValueError("canonical input must contain transparent background pixels")
    return {
        **metadata,
        "alpha_min": alpha_min,
        "alpha_max": alpha_max,
        "sha256": digest,
        "validation": "content-addressed-integrity",
    }


def validate_canonical_integrity(path: Path, input_path: str | None = None) -> dict:
    """Path wrapper for :func:`validate_canonical_integrity_bytes`."""
    if input_path is None:
        return validate_canonical_png(path)
    return validate_canonical_integrity_bytes(path.read_bytes(), input_path)


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


def _glb_json_document(path: Path) -> dict:
    """Read the JSON chunk from a GLB without importing a 3D runtime."""
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] != b"glTF":
            raise ValueError("artifact must be a GLB with glTF magic")
        while True:
            chunk_header = handle.read(8)
            if not chunk_header:
                break
            if len(chunk_header) != 8:
                raise ValueError("GLB chunk header is truncated")
            chunk_length = int.from_bytes(chunk_header[:4], "little")
            chunk_type = chunk_header[4:8]
            payload = handle.read(chunk_length)
            if len(payload) != chunk_length:
                raise ValueError("GLB chunk payload is truncated")
            if chunk_type == b"JSON":
                try:
                    value = json.loads(payload.rstrip(b"\x00 \t\r\n").decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("GLB JSON chunk is invalid") from exc
                if not isinstance(value, dict):
                    raise ValueError("GLB JSON root must be an object")
                return value
    raise ValueError("GLB is missing its JSON chunk")


def validate_glb_quality(path: Path, profile: str) -> dict:
    """Fail closed when a generated GLB loses renderable color or embedded PBR data."""
    if profile not in {"geometry", "vertex_color", "pbr_textured"}:
        raise ValueError(f"unknown GLB quality profile: {profile}")

    document = _glb_json_document(path)
    meshes = document.get("meshes")
    if not isinstance(meshes, list) or not meshes:
        raise ValueError("GLB quality guard: no meshes")

    primitives: list[dict] = []
    for mesh in meshes:
        if not isinstance(mesh, dict):
            continue
        rows = mesh.get("primitives")
        if isinstance(rows, list):
            primitives.extend(row for row in rows if isinstance(row, dict))
    if not primitives:
        raise ValueError("GLB quality guard: no mesh primitives")

    geometry = [
        primitive
        for primitive in primitives
        if isinstance(primitive.get("attributes"), dict)
        and "POSITION" in primitive["attributes"]
    ]
    if not geometry:
        raise ValueError("GLB quality guard: geometry is missing POSITION data")

    vertex_colored = [primitive for primitive in geometry if "COLOR_0" in primitive["attributes"]]
    if profile == "vertex_color" and len(vertex_colored) != len(geometry):
        raise ValueError("GLB quality guard: one or more geometry primitives are missing COLOR_0")

    materials = document.get("materials")
    textures = document.get("textures")
    images = document.get("images")
    buffer_views = document.get("bufferViews")
    if not isinstance(materials, list):
        materials = []
    if not isinstance(textures, list):
        textures = []
    if not isinstance(images, list):
        images = []
    if not isinstance(buffer_views, list):
        buffer_views = []

    def texture_is_embedded(texture_info: object) -> bool:
        if not isinstance(texture_info, dict):
            return False
        index = texture_info.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(textures):
            return False
        texture = textures[index]
        if not isinstance(texture, dict):
            return False
        source = texture.get("source")
        if source is None:
            extensions = texture.get("extensions")
            if isinstance(extensions, dict):
                for extension_name in ("EXT_texture_webp", "KHR_texture_basisu"):
                    extension = extensions.get(extension_name)
                    if isinstance(extension, dict) and "source" in extension:
                        source = extension["source"]
                        break
        if (
            not isinstance(source, int)
            or isinstance(source, bool)
            or not 0 <= source < len(images)
        ):
            return False
        image = images[source]
        if not isinstance(image, dict):
            return False
        mime = image.get("mimeType")
        buffer_view = image.get("bufferView")
        if not isinstance(mime, str) or not mime.startswith("image/"):
            return False
        if (
            not isinstance(buffer_view, int)
            or isinstance(buffer_view, bool)
            or not 0 <= buffer_view < len(buffer_views)
        ):
            return False
        view = buffer_views[buffer_view]
        return (
            isinstance(view, dict)
            and isinstance(view.get("byteLength"), int)
            and not isinstance(view.get("byteLength"), bool)
            and view["byteLength"] > 0
        )

    textured_primitives = 0
    if profile == "pbr_textured":
        for primitive in geometry:
            attributes = primitive["attributes"]
            if "TEXCOORD_0" not in attributes:
                raise ValueError("GLB quality guard: PBR geometry is missing TEXCOORD_0")
            material_index = primitive.get("material")
            if (
                not isinstance(material_index, int)
                or isinstance(material_index, bool)
                or not 0 <= material_index < len(materials)
            ):
                raise ValueError("GLB quality guard: PBR geometry has no valid material")
            material = materials[material_index]
            pbr = material.get("pbrMetallicRoughness") if isinstance(material, dict) else None
            if pbr is None:
                raise ValueError("GLB quality guard: material has no pbrMetallicRoughness")
            if not isinstance(pbr, dict):
                raise TypeError("GLB quality guard: pbrMetallicRoughness must be an object")
            if not texture_is_embedded(pbr.get("baseColorTexture")):
                raise ValueError("GLB quality guard: embedded base-color texture is missing")
            if not texture_is_embedded(pbr.get("metallicRoughnessTexture")):
                raise ValueError(
                    "GLB quality guard: embedded metallic/roughness texture is missing"
                )
            textured_primitives += 1

    return {
        "profile": profile,
        "mesh_count": len(meshes),
        "primitive_count": len(primitives),
        "geometry_primitive_count": len(geometry),
        "vertex_colored_primitive_count": len(vertex_colored),
        "pbr_textured_primitive_count": textured_primitives,
        "has_vertex_color": bool(vertex_colored),
        "has_base_color_texture": textured_primitives > 0,
        "has_metallic_roughness_texture": textured_primitives > 0,
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


def worker_identity(capability: dict) -> dict:
    """Return the cheap deployment identity checked before any paid GPU call."""
    recommended = next(
        (profile for profile in capability.get("profiles", []) if profile.get("id") == "recommended"),
        None,
    )
    if recommended is None:
        raise ValueError(f"{capability.get('id', '?')} has no recommended profile")
    if not isinstance(recommended, dict):
        raise TypeError("recommended profile must be an object")
    return {
        "model": capability["id"],
        "worker_app": capability["worker_app"],
        "output": capability["output"],
        "deployment": deepcopy(capability["deployment"]),
        "recommended_profile": {
            "id": "recommended",
            "options": deepcopy(recommended.get("options", {})),
            "quality": deepcopy(recommended.get("quality")),
        },
    }


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
    data = path.read_bytes()
    validate_canonical_integrity_bytes(data, input_path)
    return data


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
    quality_profile: str | None = None,
) -> dict:
    """Run one GPU generation job end to end inside the model container.

    Every worker exposes this same body as `Model.generate_job` so the local
    client can spawn the GPU class method directly. Canonical bytes are fully
    validated before upload; the GPU worker re-checks content-address integrity
    and alpha semantics, then validates the final artifact before returning.
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

    artifact_path = Path(ARTIFACT_ROOT) / artifact_rel
    artifact_t0 = time.perf_counter()
    try:
        metadata = validate_glb(artifact_path, expected_size)
        if quality_profile is not None:
            metadata["quality"] = validate_glb_quality(artifact_path, quality_profile)
    except Exception:
        # A failed quality guard must never make a bad artifact durable in the Volume.
        artifact_path.unlink(missing_ok=True)
        raise
    artifact_validation_s = time.perf_counter() - artifact_t0

    commit_t0 = time.perf_counter()
    artifacts_volume.commit()
    artifact_commit_s = time.perf_counter() - commit_t0
    metadata["path"] = artifact_rel.as_posix()

    timings = value.setdefault("timings", {})
    timings["job_input_validation_s"] = input_validation_s
    timings["job_artifact_validation_s"] = artifact_validation_s
    timings["job_artifact_commit_s"] = artifact_commit_s
    timings["job_total_s"] = time.perf_counter() - job_t0
    return generation_result(model_id, value, metadata)
