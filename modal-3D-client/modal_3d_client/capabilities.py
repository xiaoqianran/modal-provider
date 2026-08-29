"""Load and validate the installed modal-3D capability document."""

from __future__ import annotations

import json
from pathlib import Path

from .constants import (
    ARTIFACTS_VOLUME,
    CANONICAL_SIZE,
    CAPABILITY_KIND,
    CLIENT_INPUT_PREFIX,
    CONTRACT,
    OPERATION,
    OUTPUT_MIME,
    OUTPUT_ROLE,
    SOURCE_MAX_BYTES,
    SOURCE_MEDIA_TYPES,
    SOURCE_ROLE,
)

_CAPABILITIES_PATH = Path(__file__).parent / "capabilities.json"


class CapabilityError(RuntimeError):
    pass


class CapabilityUnavailable(CapabilityError):
    pass


class IncompatibleCapability(CapabilityError):
    pass


def _validate_document(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise IncompatibleCapability("capability document must be an object")
    doc = dict(value)
    if doc.get("contract") != CONTRACT:
        raise IncompatibleCapability("unsupported modal-3D capability contract")
    if doc.get("provider") not in (None, "modal-3d"):
        raise IncompatibleCapability("incompatible modal-3D provider identity")
    if doc.get("kind") not in (None, CAPABILITY_KIND):
        raise IncompatibleCapability("incompatible modal-3D capability kind")
    if doc.get("operation") not in (None, OPERATION):
        raise IncompatibleCapability("incompatible modal-3D operation")
    outputs = doc.get("outputs")
    if outputs is not None and outputs != [{"role": OUTPUT_ROLE, "mediaType": OUTPUT_MIME}]:
        raise IncompatibleCapability("incompatible modal-3D outputs")

    generation = doc.get("generation")
    if not isinstance(generation, dict):
        raise IncompatibleCapability("modal-3D generation descriptor is missing")
    if generation.get("job_transport") != "modal.FunctionCall":
        raise IncompatibleCapability("modal-3D job transport is incompatible")
    if generation.get("entrypoint") != "direct_class_method":
        raise IncompatibleCapability("modal-3D entrypoint is not direct class method")
    if generation.get("input_path_prefix") != CLIENT_INPUT_PREFIX:
        raise IncompatibleCapability("modal-3D input path prefix is incompatible")
    if generation.get("artifact_volume") not in (None, ARTIFACTS_VOLUME):
        raise IncompatibleCapability("modal-3D artifact volume is incompatible")
    if generation.get("artifact_path_field") not in (None, "path"):
        raise IncompatibleCapability("modal-3D artifact path field is incompatible")

    input_contract = generation.get("input_contract")
    if not isinstance(input_contract, dict):
        raise IncompatibleCapability("modal-3D canonical input contract is missing")
    expected_input = {
        "role": "canonical_rgba",
        "mime": "image/png",
        "mode": "RGBA",
        "width": CANONICAL_SIZE,
        "height": CANONICAL_SIZE,
        "bit_depth": 8,
        "layout": "letterbox",
        "alpha": "channel_required",
    }
    if input_contract != expected_input:
        raise IncompatibleCapability("modal-3D canonical input contract is incompatible")

    source = doc.get("source_input_contract")
    if source is not None:
        if source.get("role") != SOURCE_ROLE:
            raise IncompatibleCapability("modal-3D source role is incompatible")
        if source.get("maxBytes") != SOURCE_MAX_BYTES:
            raise IncompatibleCapability("modal-3D source max bytes is incompatible")
        if tuple(source.get("mediaTypes") or ()) != tuple(SOURCE_MEDIA_TYPES):
            raise IncompatibleCapability("modal-3D source media types are incompatible")

    models = doc.get("models")
    if not isinstance(models, list) or not models:
        raise IncompatibleCapability("modal-3D models are missing")
    normalized: list[dict[str, object]] = []
    for item in models:
        if not isinstance(item, dict):
            raise IncompatibleCapability("modal-3D model descriptor is invalid")
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            raise IncompatibleCapability("modal-3D model id is invalid")
        artifact = item.get("artifact")
        if not isinstance(artifact, dict):
            raise IncompatibleCapability("modal-3D model artifact contract is missing")
        if artifact.get("mime") not in (None, OUTPUT_MIME):
            raise IncompatibleCapability("modal-3D model artifact MIME is incompatible")
        if artifact.get("mediaType") not in (None, OUTPUT_MIME):
            raise IncompatibleCapability("modal-3D model artifact mediaType is incompatible")
        profiles = item.get("profiles")
        if not isinstance(profiles, list) or not profiles:
            raise IncompatibleCapability("modal-3D model profiles are missing")
        entrypoint = item.get("generation_entrypoint")
        if not isinstance(entrypoint, dict) or entrypoint.get("method_name") != "generate_job":
            raise IncompatibleCapability("modal-3D worker lacks a direct generate_job entrypoint")
        normalized.append(dict(item))
    doc["models"] = normalized
    return doc


def capabilities_document() -> dict[str, object]:
    try:
        payload = json.loads(_CAPABILITIES_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CapabilityUnavailable("modal-3D capability document is not installed") from exc
    except json.JSONDecodeError as exc:
        raise IncompatibleCapability("modal-3D capability document is not valid JSON") from exc
    return _validate_document(payload)
