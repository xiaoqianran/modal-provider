from __future__ import annotations

import threading

import modal
from modal.exception import AuthError, InternalError, PermissionDeniedError, ServiceError
from modal.exception import ConnectionError as ModalConnectionError
from modal.exception import TimeoutError as ModalTimeoutError

from .constants import APP_NAME, CAPABILITIES_FUNCTION, SUPPORTED_MODELS
from .contracts import ContractError, validate_capabilities
from .modal_session import NotConnectedError, client

_lock = threading.RLock()
_cache: dict[str, object] | None = None
_RECOVERABLE = (
    NotConnectedError,
    AuthError,
    PermissionDeniedError,
    ModalConnectionError,
    InternalError,
    ServiceError,
    ModalTimeoutError,
    TimeoutError,
)


def refresh() -> dict[str, object]:
    fn = modal.Function.from_name(APP_NAME, CAPABILITIES_FUNCTION, client=client())
    document = validate_capabilities(fn.remote())
    global _cache
    with _lock:
        _cache = document
    return document


def document(*, refresh_remote: bool = True) -> dict[str, object]:
    if refresh_remote:
        try:
            return refresh()
        except ContractError:
            raise
        except _RECOVERABLE:
            pass
    with _lock:
        if _cache is not None:
            return _cache
    raise NotConnectedError("Modal 尚未连接，且没有 capability 缓存")


def public_models() -> list[dict[str, object]]:
    doc = document()
    return [
        {
            "id": model["id"],
            "name": model["name"],
            "parameters": model.get("parameters"),
            "profiles": model["profiles"],
            "width": model["width"],
            "height": model["height"],
        }
        for model in doc["models"]
    ]


def ensure_model(model_id: str) -> None:
    # Generation hot path must stay local until the direct GPU Worker spawn.
    # If capabilities were explicitly fetched earlier, use that cached document;
    # otherwise validate against the client version's pinned model set. Never do
    # a remote capabilities() call here.
    with _lock:
        cached = _cache
    if cached is not None:
        if any(model["id"] == model_id for model in cached["models"]):
            return
        raise ContractError(f"unsupported model: {model_id}")
    if model_id not in SUPPORTED_MODELS:
        raise ContractError(f"unsupported model: {model_id}")
