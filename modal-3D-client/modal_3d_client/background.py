"""Direct client-side routing to the useful T4 background-mask worker."""

from __future__ import annotations

import base64
import binascii

import modal

from .modal_session import client

APP_NAME = "modal-3d-rembg"
CLASS_NAME = "RemBgWorker"
METHOD_NAME = "process"


def predict_mask(data: bytes) -> dict[str, object]:
    """Run BiRefNet on T4 directly; no CPU gateway or conditioning container."""
    if not data:
        raise ValueError("source image is empty")
    remote_cls = modal.Cls.from_name(APP_NAME, CLASS_NAME, client=client())
    value = getattr(remote_cls(), METHOD_NAME).remote(data)
    if not isinstance(value, dict):
        raise TypeError("background worker returned an invalid response")
    encoded = value.get("mask_bytes_b64")
    if not isinstance(encoded, str) or not encoded:
        raise TypeError("background worker returned no mask")
    try:
        mask_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("background worker returned an invalid mask encoding") from exc
    if not mask_bytes:
        raise ValueError("background worker returned an empty mask")
    return {
        "mask_bytes": mask_bytes,
        "engine": value.get("engine"),
        "elapsed_ms": value.get("elapsed_ms"),
        "source_size": value.get("source_size"),
    }
