from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import modal

from .constants import APP_NAME, ARTIFACT_FUNCTION
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

    fn = modal.Function.from_name(APP_NAME, ARTIFACT_FUNCTION, client=client())
    data = fn.remote(str(artifact["id"]))
    if not isinstance(data, bytes):
        raise ContractError("artifact function must return bytes")
    _validate_bytes(data, artifact)

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".artifact-", suffix=".part", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _validate_bytes(data: bytes, artifact: dict[str, object]) -> None:
    if len(data) != artifact["bytes"]:
        raise ContractError("artifact bytes mismatch")
    if data[:8] != PNG_SIGNATURE:
        raise ContractError("artifact is not a PNG")
    if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
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
