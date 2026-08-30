from __future__ import annotations

import hashlib
from pathlib import Path

from .constants import MODELS_VOLUME
from .models import MODELS

_MODULES = {
    "modal-2d-sana-sprint": "modal_2d.workers.sana_sprint",
    "modal-2d-qwen-image-2512": "modal_2d.workers.qwen_image_2512",
    "modal-2d-z-image-turbo": "modal_2d.workers.z_image_turbo",
    "modal-2d-hidream-o1": "modal_2d.workers.hidream_o1",
}


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
    targets = []
    seen = set()
    for model in MODELS:
        if model.worker_app in seen:
            continue
        worker_models = [item for item in MODELS if item.worker_app == model.worker_app]
        targets.append(
            {
                "app": model.worker_app,
                "module": _MODULES[model.worker_app],
                "kind": "worker",
                "revision": revision,
                "models": [item.id for item in worker_models],
                "weights": [
                    {
                        "volume": MODELS_VOLUME,
                        "requiredPaths": [
                            path
                            for item in worker_models
                            for path in (f"{item.id}/.complete", f"{item.id}/{item.snapshot_file}")
                        ],
                        "prepare": [
                            {
                                "module": "modal_2d.app",
                                "function": "prefetch",
                                "arguments": [item.id],
                            }
                            for item in worker_models
                        ],
                    }
                ],
            }
        )
        seen.add(model.worker_app)
    return {
        "provider": "modal-2d",
        "targets": targets,
        "utilities": [
            {
                "app": "modal-2d-prefetch",
                "module": "modal_2d.app",
                "kind": "prefetch",
                "default": False,
                "revision": revision,
            }
        ],
    }
