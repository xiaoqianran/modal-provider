"""Static GPU worker routing table.

The client spawns `Model.generate_job` on each model's own Modal App. There is
no gateway and no remote registry: a submission is one hop, from this process
straight onto the GPU container.
"""

from __future__ import annotations

import modal

from .constants import CLIENT_INPUT_PREFIX
from .modal_session import client

# model_id -> (modal app, class name, method name)
WORKERS: dict[str, tuple[str, str, str]] = {
    "fastsam3d-plus-plus": ("modal-3d-fastsam3d", "Model", "generate_job"),
    "hunyuan2.1-plus-plus": ("modal-3d-hunyuan", "Model", "generate_job"),
    "hermit-trellis2-plus-plus": ("modal-3d-hermit-trellis2-plus-plus", "Model", "generate_job"),
    "pixal3d": ("modal-3d-pixal3d", "Model", "generate_job"),
}

DIRECT_ENTRYPOINT = "generate_job"


def known_models() -> list[str]:
    return sorted(WORKERS)


def resolve(model: str) -> tuple[str, str, str]:
    entry = WORKERS.get(model)
    if entry is None:
        raise ValueError(f"unknown model: {model}")
    return entry


def assert_client_input_path(input_path: str) -> str:
    """Reject anything that is not a locally uploaded canonical input."""
    if not input_path.startswith(CLIENT_INPUT_PREFIX):
        raise ValueError(f"input_path must start with {CLIENT_INPUT_PREFIX}")
    if ".." in input_path.split("/") or input_path.startswith("/"):
        raise ValueError("input_path must be relative and free of traversal")
    return input_path


def spawn_warmup(model: str):
    """Start the selected GPU Model container without running inference."""
    app_name, class_name, _method_name = resolve(model)
    remote_cls = modal.Cls.from_name(app_name, class_name, client=client())
    return remote_cls().warmup.spawn()


def spawn_generation(model: str, input_path: str, options: dict | None = None):
    """Spawn `Model.generate_job` and return its `modal.FunctionCall`.

    Persist `call.object_id` locally; restore it later with
    `modal.functions.FunctionCall.from_id(...)`.
    """
    app_name, class_name, method_name = resolve(model)
    assert_client_input_path(input_path)
    remote_cls = modal.Cls.from_name(app_name, class_name, client=client())
    method = getattr(remote_cls(), method_name)
    return method.spawn(input_path, dict(options or {}))
