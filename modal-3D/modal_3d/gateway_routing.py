"""Worker routing helpers for the 3D gateway.

This module owns Modal worker lookup and request identity. It deliberately knows
nothing about task persistence or HTTP endpoints.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import modal

from .capabilities import capabilities_document


def public_capabilities(registry) -> dict:
    """Return the client contract without internal worker-routing metadata."""
    document = capabilities_document(registry)
    # Keep this defensive filter at the deployment boundary as well as in the
    # capability builder: old registry entries can survive code redeploys.
    for model in document.get("models", []):
        if isinstance(model, dict):
            model.pop("generation_entrypoint", None)
    return document


def normalize_input_path(input_path: str) -> str:
    """Normalize and confine a gateway input to a supported provider namespace."""
    rel = Path(input_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("input_path must be relative to /artifacts")
    if not rel.parts or rel.parts[0] not in {"client-inputs", "source-inputs"}:
        raise ValueError("input_path must be under client-inputs/ or source-inputs/")
    return rel.as_posix()


def generation_job_key(model: str, input_path: str, options: dict) -> str:
    """Stable content key used only to deduplicate in-flight generation work."""
    payload = json.dumps(
        {"model": model, "input_path": input_path, "options": options},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def spawn_generation(capability: dict, input_path: str, options: dict):
    """Spawn the worker entrypoint advertised by a capability.

    Workers may opt into a direct class-method entrypoint. Older workers keep
    using the normalized adapter Function, so adding a new routing mode does not
    require changing the gateway submission flow.
    """
    entrypoint = capability.get("generation_entrypoint")
    if entrypoint is not None:
        remote_cls = modal.Cls.from_name(capability["worker_app"], entrypoint["class_name"])
        method = getattr(remote_cls(), entrypoint["method_name"])
        return method.spawn(input_path, options)

    fn = modal.Function.from_name(capability["worker_app"], "generate")
    return fn.spawn(input_path, options)
