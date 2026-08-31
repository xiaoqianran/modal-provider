from __future__ import annotations

import hashlib
from pathlib import Path


def runtime_revision() -> str:
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256-{digest.hexdigest()[:32]}"


def deployment_manifest() -> dict[str, object]:
    revision = runtime_revision()
    return {
        "provider": "modal-world",
        "targets": [
            {
                "app": "modal-world",
                "module": "modal_world.app",
                "kind": "pipeline",
                "revision": revision,
                "models": ["hyworld2"],
            },
            {
                "app": "modal-world-stage2",
                "module": "modal_world.stage2_app",
                "kind": "worker",
                "revision": revision,
                "models": ["hyworld2"],
            },
            {
                "app": "modal-world-stage3",
                "module": "modal_world.stage3_app",
                "kind": "worker",
                "revision": revision,
                "models": ["hyworld2"],
            },
        ],
    }
