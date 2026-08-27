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

from .constants import ARTIFACTS_VOLUME, CANONICAL_SIZE, OUTPUT_MIME, OUTPUT_ROLE
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


def validate_canonical_png(data: bytes) -> dict[str, object]:
    if not data:
        raise ContractError("canonical PNG is empty")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.format != "PNG":
                raise ContractError("canonical input must be PNG")
            if image.size != (CANONICAL_SIZE, CANONICAL_SIZE):
                raise ContractError(f"canonical PNG must be {CANONICAL_SIZE}x{CANONICAL_SIZE}")
            if image.mode != "RGBA":
                raise ContractError("canonical PNG must be RGBA")
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError("canonical PNG is invalid") from exc
    sha256 = hashlib.sha256(data).hexdigest()
    return {"bytes": len(data), "sha256": sha256, "digest": f"sha256:{sha256}"}


def upload_canonical(data: bytes) -> dict[str, object]:
    descriptor = validate_canonical_png(data)
    path = f"client-inputs/{descriptor['sha256']}.png"
    with _volume().batch_upload(force=True) as batch:
        batch.put_file(io.BytesIO(data), path)
    return {**descriptor, "path": path}


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
    artifact = validate_artifact(descriptor, model=model)
    sha256 = str(artifact["sha256"])
    path = _cache_path(sha256)
    if not path.is_file():
        raise FileNotFoundError(path)
    _validate_glb(path, int(artifact["bytes"]))
    if _sha256_file(path) != sha256:
        raise ContractError("cached artifact SHA-256 mismatch")
    path.touch()
    return _public_descriptor(artifact, model, sha256), path
