"""Local routing table for direct 3D operation submission.

The legacy generation API is preserved, while the same route table can now host
mesh-to-mesh and asset-processing operations with different method names.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import modal

from .common import CLIENT_INPUT_NAMESPACE

ROUTES: dict[str, tuple[str, str, str]] = {
    "fastsam3d-plus-plus": ("modal-3d-fastsam3d", "Model", "generate_job"),
    "hunyuan2.1-plus-plus": ("modal-3d-hunyuan", "Model", "generate_job"),
    "hermit-trellis2-plus-plus": (
        "modal-3d-hermit-trellis2-plus-plus",
        "Model",
        "generate_job",
    ),
    "pixal3d": ("modal-3d-pixal3d", "Model", "generate_job"),
}

WORKERS = dict(ROUTES)

# Operation models never appear in the legacy image-generation list.
from .operations import SPECS, safe_relative, worker_for

ROUTES.update({name: (worker_for(name), "Model", "run_job") for name in SPECS})


def known_models() -> list[str]:
    return sorted(WORKERS)


def known_capabilities() -> list[str]:
    return sorted(ROUTES)


def resolve(capability_id: str) -> tuple[str, str, str]:
    """Legacy model resolver retained for installed generation clients."""
    entry = WORKERS.get(capability_id)
    if entry is None:
        raise ValueError(f"unknown model: {capability_id}")
    return entry


def resolve_capability(capability_id: str) -> tuple[str, str, str]:
    entry = ROUTES.get(capability_id)
    if entry is None:
        raise ValueError(f"unknown capability: {capability_id}")
    return entry


def normalize_artifact_path(input_path: str) -> str:
    """Confine any operation input to a relative path below /artifacts."""
    return safe_relative(input_path)


def normalize_input_path(input_path: str, *, namespace: str = CLIENT_INPUT_NAMESPACE) -> str:
    """Legacy image-generation guard: inputs must remain under client-inputs/."""
    relative = normalize_artifact_path(input_path)
    rel = Path(relative)
    if rel.parts[0] != namespace:
        raise ValueError(f"input_path must be under {namespace}/")
    return relative


def generation_job_key(model: str, input_path: str, options: dict) -> str:
    """Stable legacy key. Keep byte-for-byte semantics for current clients."""
    payload = json.dumps(
        {"model": model, "input_path": input_path, "options": options},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_operation_inputs(inputs: dict[str, str]) -> dict[str, str]:
    """Validate named operation inputs and confine every path below /artifacts."""
    if not isinstance(inputs, dict) or not inputs:
        raise TypeError("operation inputs must be a non-empty object")
    normalized: dict[str, str] = {}
    for name, path in sorted(inputs.items()):
        if not isinstance(name, str) or not name:
            raise ValueError("operation input names must be non-empty strings")
        if not isinstance(path, str) or not path:
            raise ValueError(f"operation input {name!r} path must be a non-empty string")
        normalized[name] = normalize_artifact_path(path)
    return normalized


def operation_job_key(
    capability_id: str,
    operation: str,
    inputs: dict[str, str],
    options: dict,
) -> str:
    """Stable content key for generic 3D operations with named inputs."""
    normalized_inputs = normalize_operation_inputs(inputs)
    payload = json.dumps(
        {
            "capability": capability_id,
            "operation": operation,
            "inputs": normalized_inputs,
            "options": options,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _spawn_direct(
    capability_id: str,
    input_payload,
    options: dict | None,
    *,
    client=None,
):
    app_name, class_name, method_name = resolve_capability(capability_id)
    lookup = {} if client is None else {"client": client}
    remote_cls = modal.Cls.from_name(app_name, class_name, **lookup)
    method = getattr(remote_cls(), method_name)
    return method.spawn(input_payload, dict(options or {}))


def spawn_operation(
    capability_id: str,
    inputs: dict[str, str],
    options: dict | None = None,
    *,
    client=None,
):
    """Spawn a generic operation with named artifact-relative inputs."""
    normalized_inputs = normalize_operation_inputs(inputs)
    return _spawn_direct(capability_id, normalized_inputs, options, client=client)


def spawn_generation(
    model: str,
    input_path: str,
    options: dict | None = None,
    *,
    client=None,
    namespace: str = CLIENT_INPUT_NAMESPACE,
):
    """Spawn the existing image-to-3D Model.generate_job path unchanged."""
    if model not in WORKERS:
        raise ValueError(f"unknown model: {model}")
    relative_path = normalize_input_path(input_path, namespace=namespace)
    return _spawn_direct(model, relative_path, options, client=client)
