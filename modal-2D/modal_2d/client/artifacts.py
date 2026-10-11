from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

import modal

from .constants import ARTIFACT_VOLUME, LEGACY_ARTIFACT_VOLUME
from .contracts import ContractError, validate_artifact
from .modal_session import client
from .storage import data_dir

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def cache_path(sha256: str) -> Path:
    if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
        raise ContractError("artifact sha256 is invalid")
    return data_dir() / "cache" / "sha256" / sha256[:2] / sha256


def fetch(descriptor: dict[str, object]) -> Path:
    artifact = validate_artifact(descriptor)
    digest = str(artifact["sha256"])
    destination = cache_path(digest)
    if destination.is_file():
        _validate_file(destination, artifact)
        destination.touch()
        return destination

    remote_path = artifact.get("remote_path")
    if not isinstance(remote_path, str):
        raise ContractError("artifact remote_path is required for direct Volume transport")
    return _cache_chunks(_volume_chunks(remote_path), destination, artifact)


def _volume_chunks(remote_path: str) -> Iterable[bytes]:
    volume_name = (
        LEGACY_ARTIFACT_VOLUME if remote_path.startswith("generated/") else ARTIFACT_VOLUME
    )
    volume = modal.Volume.from_name(volume_name, client=client())
    return volume.read_file(remote_path)


def _cache_chunks(chunks: Iterable[bytes], destination: Path, artifact: dict[str, object]) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".artifact-", suffix=".part", dir=destination.parent
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    total = 0
    signature = bytearray()
    try:
        with os.fdopen(fd, "wb") as stream:
            for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise ContractError("artifact transport must yield bytes")
                if len(signature) < len(PNG_SIGNATURE):
                    signature.extend(chunk[: len(PNG_SIGNATURE) - len(signature)])
                total += len(chunk)
                digest.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        _validate_stream_result(bytes(signature), total, digest.hexdigest(), artifact)
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def _validate_stream_result(
    signature: bytes, size: int, digest: str, artifact: dict[str, object]
) -> None:
    if size != artifact["bytes"]:
        raise ContractError("artifact bytes mismatch")
    if signature != PNG_SIGNATURE:
        raise ContractError("artifact is not a PNG")
    if digest != artifact["sha256"]:
        raise ContractError("artifact SHA-256 mismatch")


def _validate_file(path: Path, artifact: dict[str, object]) -> None:
    if path.stat().st_size != artifact["bytes"]:
        path.unlink(missing_ok=True)
        raise ContractError("cached artifact bytes mismatch")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        signature = stream.read(8)
        digest.update(signature)
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if signature != PNG_SIGNATURE or digest.hexdigest() != artifact["sha256"]:
        path.unlink(missing_ok=True)
        raise ContractError("cached artifact integrity check failed")
