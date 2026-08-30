from __future__ import annotations

import re

from .constants import OPERATION, OUTPUT_MIME, OUTPUT_ROLE

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    pass


def validate_artifact(value: object, *, model: str, require_path: bool = True) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ContractError("artifact must be an object")
    artifact = dict(value)
    sha256 = artifact.get("sha256")
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        raise ContractError("artifact.sha256 is invalid")
    size = artifact.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ContractError("artifact.bytes is invalid")
    if artifact.get("mime") not in (None, OUTPUT_MIME):
        raise ContractError("artifact.mime is incompatible")
    if artifact.get("mediaType") not in (None, OUTPUT_MIME):
        raise ContractError("artifact.mediaType is incompatible")
    if artifact.get("digest") not in (None, f"sha256:{sha256}"):
        raise ContractError("artifact.digest does not match sha256")
    if artifact.get("role") not in (None, OUTPUT_ROLE):
        raise ContractError("artifact.role is incompatible")
    path = artifact.get("path")
    if require_path and (not isinstance(path, str) or not path):
        raise ContractError("artifact.path is required")
    if path is not None and (not isinstance(path, str) or not path):
        raise ContractError("artifact.path is invalid")
    producer = artifact.get("producer")
    if producer is not None:
        if not isinstance(producer, dict):
            raise ContractError("artifact.producer is invalid")
        if producer.get("provider") not in (None, "modal-3d"):
            raise ContractError("artifact.producer.provider is incompatible")
        if producer.get("operation") not in (None, OPERATION):
            raise ContractError("artifact.producer.operation is incompatible")
        if producer.get("model") not in (None, model):
            raise ContractError("artifact.producer.model is incompatible")
    return artifact
