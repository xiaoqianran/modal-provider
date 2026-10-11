from __future__ import annotations

from .models import options_for
from .workers import spawn_generation, spawn_warmup


def prefetch(model: str):
    """Asynchronously cold-start the selected GPU model before input conditioning finishes."""
    return spawn_warmup(model)


def submit(model: str, input_path: str, profile: str, seed: int):
    """Spawn the GPU job and return its `modal.FunctionCall`.

    The caller persists `call.object_id` as the task id. Nothing else is
    submitted: option validation, routing, idempotency and task state are local, and the
    spawn goes straight to `Model.generate_job`.
    """
    options = options_for(model, profile, seed)
    return spawn_generation(model, input_path, options)
