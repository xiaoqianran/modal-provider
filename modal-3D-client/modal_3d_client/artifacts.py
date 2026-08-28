from __future__ import annotations

import hashlib
import io
import os
import struct
import tempfile
import uuid
from pathlib import Path, PurePosixPath

import modal
from PIL import Image

from . import background
from .conditioning import BackgroundMaskRequired, condition_image
from .constants import (
    ARTIFACTS_VOLUME,
    CLIENT_INPUT_PREFIX,
    OUTPUT_MIME,
    OUTPUT_ROLE,
    SOURCE_MAX_BYTES,
)
from .contracts import ContractError, validate_artifact
from .modal_session import client
from .storage import data_dir

_CHUNK_SIZE = 1024 * 1024


def _volume() -> modal.Volume:
    return modal.Volume.from_name(ARTIFACTS_VOLUME, client=client())


def _safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ContractError("artifact path is unsafe")
    return path.as_posix()


def validate_source_image(data: bytes) -> dict[str, object]:
    if not data:
        raise ContractError("source image is empty")
    if len(data) > SOURCE_MAX_BYTES:
        raise ContractError("source image exceeds 20 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            image_format = image.format
            width, height = image.size
            mode = image.mode
    except Exception as exc:
        raise ContractError("source image could not be decoded") from exc
    formats = {
        "PNG": ("image/png", ".png"),
        "JPEG": ("image/jpeg", ".jpg"),
        "WEBP": ("image/webp", ".webp"),
    }
    if image_format not in formats:
        raise ContractError(f"unsupported source image format: {image_format}")
    if width <= 0 or height <= 0:
        raise ContractError("source image dimensions are invalid")
    media_type, extension = formats[image_format]
    sha256 = hashlib.sha256(data).hexdigest()
    return {
        "bytes": len(data),
        "sha256": sha256,
        "digest": f"sha256:{sha256}",
        "mediaType": media_type,
        "extension": extension,
        "width": width,
        "height": height,
        "mode": mode,
    }


_CONDITIONING_EVIDENCE_FIELDS = (
    "strategy",
    "source_sha256",
    "canonical_sha256",
    "source_format",
    "source_size",
    "foreground_bbox",
    "foreground_ratio",
    "canonical_size",
    "engine",
    "mask_elapsed_ms",
)


def upload_source(data: bytes, *, mask: bytes | None = None) -> dict[str, object]:
    """Condition the source locally, then upload the finished canonical RGBA.

    Modal workers only accept `client-inputs/`. Existing alpha or a caller mask
    is handled entirely locally. Opaque sources without a mask call the T4
    `RemBgWorker.process` method directly, then canonicalization stays local.
    """
    descriptor = validate_source_image(data)
    if mask is not None:
        conditioned = condition_image(data, mask)
    else:
        try:
            conditioned = condition_image(data)
        except BackgroundMaskRequired:
            prediction = background.predict_mask(data)
            conditioned = condition_image(data, bytes(prediction["mask_bytes"]))
            conditioned["engine"] = prediction.get("engine")
            conditioned["mask_elapsed_ms"] = prediction.get("elapsed_ms")
    canonical = bytes(conditioned["canonical_bytes"])
    path = f"{CLIENT_INPUT_PREFIX}{conditioned['canonical_sha256']}.png"
    with _volume().batch_upload(force=True) as batch:
        batch.put_file(io.BytesIO(canonical), path)
    evidence = {
        key: conditioned[key] for key in _CONDITIONING_EVIDENCE_FIELDS if key in conditioned
    }
    return {**descriptor, "path": path, "canonical_bytes": len(canonical), "conditioning": evidence}


def _cache_path(sha256: str) -> Path:
    if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
        raise ContractError("artifact SHA-256 is invalid")
    root = data_dir() / "cache" / "sha256"
    path = root / sha256[:2] / sha256
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _validate_glb(path: Path, expected_bytes: int) -> None:
    actual = path.stat().st_size
    if actual != expected_bytes:
        raise ContractError("artifact bytes mismatch")
    with path.open("rb") as handle:
        header = handle.read(12)
    if len(header) != 12:
        raise ContractError("artifact GLB is truncated")
    magic, version, declared = struct.unpack("<4sII", header)
    if magic != b"glTF" or version != 2 or declared != actual:
        raise ContractError("artifact is not glTF Binary v2")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_artifact_id(model: str, sha256: str) -> str:
    identity = uuid.uuid5(uuid.NAMESPACE_URL, f"modal-3d:artifact:{model}:{sha256}").hex
    return f"art_{identity}"


def fetch(descriptor: object, *, model: str) -> tuple[dict[str, object], Path]:
    artifact = validate_artifact(descriptor, model=model)
    sha256 = str(artifact["sha256"])
    destination = _cache_path(sha256)
    if destination.is_file():
        _validate_glb(destination, int(artifact["bytes"]))
        if _sha256_file(destination) != sha256:
            raise ContractError("cached artifact SHA-256 mismatch")
        destination.touch()
        return _public_descriptor(artifact, model, sha256), destination

    remote_path = _safe_path(str(artifact["path"]))
    fd, temporary_name = tempfile.mkstemp(prefix=".artifact-", suffix=".part", dir=destination.parent)
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(fd, "wb") as stream:
            for chunk in _volume().read_file(remote_path):
                if not isinstance(chunk, bytes):
                    raise ContractError("artifact transport must yield bytes")
                stream.write(chunk)
                digest.update(chunk)
                total += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        _validate_glb(temporary, int(artifact["bytes"]))
        if total != int(artifact["bytes"]) or digest.hexdigest() != sha256:
            raise ContractError("artifact integrity check failed")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return _public_descriptor(artifact, model, sha256), destination


def _public_descriptor(
    artifact: dict[str, object], model: str, sha256: str
) -> dict[str, object]:
    public = {key: value for key, value in artifact.items() if key != "path"}
    public.update(
        {
            "id": public.get("id") or _legacy_artifact_id(model, sha256),
            "role": OUTPUT_ROLE,
            "mediaType": OUTPUT_MIME,
            "digest": f"sha256:{sha256}",
            "mime": OUTPUT_MIME,
            "sha256": sha256,
        }
    )
    return public


def cached(descriptor: object, *, model: str) -> tuple[dict[str, object], Path]:
    artifact = validate_artifact(descriptor, model=model, require_path=False)
    sha256 = str(artifact["sha256"])
    path = _cache_path(sha256)
    if not path.is_file():
        raise FileNotFoundError(path)
    _validate_glb(path, int(artifact["bytes"]))
    if _sha256_file(path) != sha256:
        raise ContractError("cached artifact SHA-256 mismatch")
    path.touch()
    return _public_descriptor(artifact, model, sha256), path
