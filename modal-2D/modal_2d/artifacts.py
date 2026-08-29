from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from .constants import (
    ARTIFACT_FORMAT,
    ARTIFACT_MIME,
    ARTIFACT_ROLE,
    IMAGE_SIZE,
    OPERATION,
    PROVIDER,
)
from .contracts import validate_artifact_id

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IHDR = b"IHDR"


def inspect_png_header(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != PNG_SIGNATURE:
        raise ValueError("generated artifact is not a PNG")
    if int.from_bytes(data[8:12], "big") != 13 or data[12:16] != IHDR:
        raise ValueError("generated PNG is missing a valid IHDR")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if (width, height) != (IMAGE_SIZE, IMAGE_SIZE):
        raise ValueError(f"generated PNG must be {IMAGE_SIZE}x{IMAGE_SIZE}")
    return width, height


def write_png(root: Path, data: bytes) -> dict[str, object]:
    width, height = inspect_png_header(data)
    sha256 = hashlib.sha256(data).hexdigest()
    artifact_id = f"art_{uuid.uuid4().hex}"
    relative = Path("generated") / f"{artifact_id}.png"
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".png.part")
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "id": artifact_id,
        "role": ARTIFACT_ROLE,
        "mediaType": ARTIFACT_MIME,
        "digest": f"sha256:{sha256}",
        "producer": {"provider": PROVIDER, "operation": OPERATION},
        # Legacy aliases remain until all consumers migrate to the shared descriptor.
        "mime": ARTIFACT_MIME,
        "format": ARTIFACT_FORMAT,
        "bytes": len(data),
        "sha256": sha256,
        "width": width,
        "height": height,
        "remote_path": relative.as_posix(),
    }


def artifact_path(root: Path, artifact_id: str) -> Path:
    return root / "generated" / f"{validate_artifact_id(artifact_id)}.png"
