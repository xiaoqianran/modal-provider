"""Local routing table for direct GPU worker submission.

There is no gateway App and no dynamic Modal Dict registry. The local client or
VPS resolves a model id to a Modal App + class + method from this static table
and spawns the GPU method directly, so a submission never pays for a CPU
container that only forwards work.

The table is the client-side mirror of each worker's `generation_entrypoint`
capability field. Keep the two in sync when adding a worker.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import modal

from .common import ARTIFACT_ROOT, CLIENT_INPUT_NAMESPACE

# model_id -> (modal app name, class name, method name)
WORKERS: dict[str, tuple[str, str, str]] = {
    "fastsam3d-plus-plus": ("modal-3d-fastsam3d", "Model", "generate_job"),
    "hunyuan2.1-plus-plus": ("modal-3d-hunyuan", "Model", "generate_job"),
    "hermit-trellis2-plus-plus": ("modal-3d-hermit-trellis2-plus-plus", "Model", "generate_job"),
    "pixal3d": ("modal-3d-pixal3d", "Model", "generate_job"),
}


def known_models() -> list[str]:
    return sorted(WORKERS)


def resolve(model: str) -> tuple[str, str, str]:
    entry = WORKERS.get(model)
    if entry is None:
        raise ValueError(f"unknown model: {model}")
    return entry


def normalize_input_path(input_path: str, *, namespace: str = CLIENT_INPUT_NAMESPACE) -> str:
    """Confine a submission path to the client-uploaded canonical namespace."""
    rel = Path(input_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"input_path must be relative to {ARTIFACT_ROOT}")
    if not rel.parts or rel.parts[0] != namespace:
        raise ValueError(f"input_path must be under {namespace}/")
    return rel.as_posix()


def generation_job_key(model: str, input_path: str, options: dict) -> str:
    """Stable content key used only to deduplicate in-flight generation work."""
    payload = json.dumps(
        {"model": model, "input_path": input_path, "options": options},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def spawn_generation(
    model: str,
    input_path: str,
    options: dict | None = None,
    *,
    client=None,
    namespace: str = CLIENT_INPUT_NAMESPACE,
):
    """Spawn `Model.generate_job` on the GPU worker for `model`.

    Returns the `modal.FunctionCall`; persist `call.object_id` locally as the
    task id and restore it later with `modal.functions.FunctionCall.from_id()`.
    """
    app_name, class_name, method_name = resolve(model)
    # Validate the path locally first: a rejected namespace must never reach
    # Modal, where a bad lookup could still start a container.
    relative_path = normalize_input_path(input_path, namespace=namespace)
    lookup = {} if client is None else {"client": client}
    remote_cls = modal.Cls.from_name(app_name, class_name, **lookup)
    method = getattr(remote_cls(), method_name)
    return method.spawn(relative_path, dict(options or {}))
