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
        "provider": "modal-3d",
        "targets": [
            {
                "app": "modal-3d-rembg",
                "module": "modal_3d.rembg_worker",
                "kind": "preprocess",
                "required": True,
                "revision": revision,
            },
            {
                "app": "modal-3d-fastsam3d",
                "module": "modal_3d.fastsam3d_plus_plus",
                "kind": "worker",
                "models": ["fastsam3d-plus-plus"],
                "revision": revision,
            },
            {
                "app": "modal-3d-hunyuan",
                "module": "modal_3d.hunyuan2_1_plus_plus",
                "kind": "worker",
                "models": ["hunyuan2.1-plus-plus"],
                "revision": revision,
            },
            {
                "app": "modal-3d-hermit-trellis2-plus-plus",
                "module": "modal_3d.hermit_trellis2_plus_plus",
                "kind": "worker",
                "models": ["hermit-trellis2-plus-plus"],
                "revision": revision,
            },
            {
                "app": "modal-3d-pixal3d",
                "module": "modal_3d.pixal3d",
                "kind": "worker",
                "models": ["pixal3d"],
                "revision": revision,
            },
        ],
    }
