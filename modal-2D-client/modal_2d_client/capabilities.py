from __future__ import annotations

import threading

from modal_2d.capabilities import capabilities_document

from .contracts import ContractError, validate_capabilities

_lock = threading.RLock()
_cache: dict[str, object] | None = None


def refresh() -> dict[str, object]:
    """Load the capability contract locally; this never starts a Modal container."""
    document = validate_capabilities(capabilities_document())
    global _cache
    with _lock:
        _cache = document
    return document


def document(*, refresh_remote: bool = True) -> dict[str, object]:
    del refresh_remote  # compatibility: capability discovery is intentionally local now.
    with _lock:
        if _cache is not None:
            return _cache
    return refresh()


def public_models() -> list[dict[str, object]]:
    doc = document(refresh_remote=False)
    return [
        {
            "id": model["id"],
            "name": model["name"],
            "parameters": model.get("parameters"),
            "profiles": model["profiles"],
            "width": model["width"],
            "height": model["height"],
            "gpu": model.get("gpu", "L40S"),
        }
        for model in doc["models"]
    ]


def ensure_model(model_id: str) -> None:
    doc = document(refresh_remote=False)
    if any(model["id"] == model_id for model in doc["models"]):
        return
    raise ContractError(f"unsupported model: {model_id}")


def worker_route(model_id: str) -> tuple[str, str, str, str]:
    doc = document(refresh_remote=False)
    for model in doc["models"]:
        if model["id"] != model_id:
            continue
        route = model["generation_entrypoint"]
        return (
            str(route["app"]),
            str(route["class_name"]),
            str(route["generate_method"]),
            str(route["batch_generate_method"]),
        )
    raise ContractError(f"unsupported model: {model_id}")
