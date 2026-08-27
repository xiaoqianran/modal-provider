from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import modal

from .constants import (
    ARTIFACTS_VOLUME,
    CAPABILITIES_FUNCTION,
    CAPABILITY_KIND,
    CONTRACT,
    GATEWAY_APP,
    GATEWAY_SUBMIT,
    JOB_TRANSPORT,
    OPERATION,
    OUTPUT_MIME,
    OUTPUT_ROLE,
    SOURCE_MAX_BYTES,
    SOURCE_MEDIA_TYPES,
    SOURCE_PATH_PREFIX,
    SOURCE_ROLE,
)
from .modal_session import client
from .storage import data_dir

_CACHE_TTL_SECONDS = 300
_cache_lock = threading.RLock()
_cache: dict[str, object] | None = None
_cache_at = 0.0
_refreshing = False


class CapabilityError(RuntimeError):
    pass


class CapabilityUnavailable(CapabilityError):
    pass


class IncompatibleCapability(CapabilityError):
    pass


def _cache_path() -> Path:
    return data_dir() / "capabilities.json"


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
    expected = {
        "app": GATEWAY_APP,
        "submit_function": GATEWAY_SUBMIT,
        "job_transport": JOB_TRANSPORT,
    }
    if any(generation.get(key) != item for key, item in expected.items()):
        raise IncompatibleCapability("modal-3D gateway identity is incompatible")
    if generation.get("artifact_volume") not in (None, ARTIFACTS_VOLUME):
        raise IncompatibleCapability("modal-3D artifact volume is incompatible")
    if generation.get("artifact_path_field") not in (None, "path"):
        raise IncompatibleCapability("modal-3D artifact path field is incompatible")

    public_input = generation.get("public_input_contract")
    if not isinstance(public_input, dict):
        raise IncompatibleCapability("modal-3D public input contract is missing")
    expected_input = {
        "role": SOURCE_ROLE,
        "mediaTypes": list(SOURCE_MEDIA_TYPES),
        "maxBytes": SOURCE_MAX_BYTES,
        "alpha": "optional",
        "conditioning": "provider",
        "pathPrefix": SOURCE_PATH_PREFIX,
    }
    if public_input != expected_input:
        raise IncompatibleCapability("modal-3D public input contract is incompatible")

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
        normalized.append(dict(item))
    doc["models"] = normalized
    return doc


def _write_cache(document: dict[str, object]) -> None:
    path = _cache_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def _read_cache() -> dict[str, object] | None:
    try:
        value = json.loads(_cache_path().read_text(encoding="utf-8"))
        return _validate_document(value)
    except (OSError, ValueError, json.JSONDecodeError, CapabilityError):
        return None


def refresh_capabilities() -> dict[str, object]:
    fn = modal.Function.from_name(GATEWAY_APP, CAPABILITIES_FUNCTION, client=client())
    try:
        value = fn.remote()
    except Exception as exc:
        raise CapabilityUnavailable("modal-3D capability discovery failed") from exc
    document = _validate_document(value)
    global _cache, _cache_at
    with _cache_lock:
        _cache = document
        _cache_at = time.monotonic()
    _write_cache(document)
    return document


def _background_refresh() -> None:
    global _refreshing
    try:
        refresh_capabilities()
    except CapabilityError:
        pass
    finally:
        with _cache_lock:
            _refreshing = False


def capabilities_document(*, refresh: bool = False) -> dict[str, object]:
    global _cache, _refreshing
    with _cache_lock:
        if _cache is None:
            _cache = _read_cache()
        cached = _cache
        fresh = cached is not None and (time.monotonic() - _cache_at) < _CACHE_TTL_SECONDS
        if cached is not None and not refresh:
            if not fresh and not _refreshing:
                _refreshing = True
                threading.Thread(target=_background_refresh, daemon=True).start()
            return cached
    return refresh_capabilities()


def public_models() -> list[dict[str, object]]:
    return [dict(item) for item in capabilities_document()["models"]]  # type: ignore[index]


def _model(model_id: str) -> dict[str, object]:
    for model in public_models():
        if model.get("id") == model_id and model.get("status") == "enabled":
            return model
    raise CapabilityError(f"modal-3D model is unavailable: {model_id}")


def options_for(model_id: str, profile_id: str, seed: int) -> dict[str, object]:
    model = _model(model_id)
    for profile in model["profiles"]:  # type: ignore[index]
        if isinstance(profile, dict) and profile.get("id") == profile_id:
            options = dict(profile.get("options") or {})
            options["seed"] = seed
            return options
    raise CapabilityError(f"modal-3D profile is unavailable: {model_id}/{profile_id}")
