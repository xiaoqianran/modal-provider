from __future__ import annotations

import modal

from .constants import GATEWAY_APP, GATEWAY_SUBMIT
from .modal_session import client
from .models import IncompatibleCapability, options_for


def submit(model: str, input_path: str, profile: str, seed: int) -> dict[str, object]:
    fn = modal.Function.from_name(GATEWAY_APP, GATEWAY_SUBMIT, client=client())
    value = fn.remote(model, input_path, options_for(model, profile, seed))
    if not isinstance(value, dict):
        raise IncompatibleCapability("gateway submission must be an object")
    task_id = value.get("task_id")
    if (
        value.get("model") != model
        or value.get("status") != "running"
        or not isinstance(task_id, str)
        or not task_id
        or value.get("call_id") != task_id
    ):
        raise IncompatibleCapability("gateway returned an invalid submission state")
    return dict(value)
