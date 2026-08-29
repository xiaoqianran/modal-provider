from __future__ import annotations

import io
from pathlib import Path


def model_snapshot_ready(path: Path, required_file: str) -> bool:
    return (path / ".complete").is_file() and (path / required_file).is_file()


def encode_png(image, request: dict[str, object]) -> bytes:
    validate_image_size(image, request)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def validate_image_size(image, request: dict[str, object]) -> None:
    expected = (int(request["width"]), int(request["height"]))
    actual = getattr(image, "size", None)
    if actual != expected:
        raise RuntimeError(f"unexpected image size: {actual} != {expected}")
