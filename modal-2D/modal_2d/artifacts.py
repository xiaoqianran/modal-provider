from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from .contracts import (
    ARTIFACT_FORMAT,
    ARTIFACT_MIME,
    ARTIFACT_ROLE,
    IMAGE_SIZE,
    validate_artifact_id,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_png(root: Path, data: bytes) -> dict[str, object]:
    if len(data) < len(PNG_SIGNATURE) or data[:8] != PNG_SIGNATURE:
        raise ValueError("generated artifact is not a PNG")
    digest = hashlib.sha256(data).hexdigest()
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
        "mime": ARTIFACT_MIME,
        "format": ARTIFACT_FORMAT,
        "bytes": len(data),
        "sha256": digest,
        "width": IMAGE_SIZE,
        "height": IMAGE_SIZE,
        "remote_path": relative.as_posix(),
    }


def artifact_path(root: Path, artifact_id: str) -> Path:
    return root / "generated" / f"{validate_artifact_id(artifact_id)}.png"
