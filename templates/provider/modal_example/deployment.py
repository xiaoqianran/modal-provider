from hashlib import sha256
from pathlib import Path

from .models import list_models


def deployment_manifest() -> dict[str, object]:
    root = Path(__file__).parent
    digest = sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(
            path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes()
        )
    models = list_models()
    targets = []
    for app in sorted({model.worker_app for model in models}):
        group = [model for model in models if model.worker_app == app]
        targets.append(
            {
                "app": app,
                "module": group[0].worker_module,
                "kind": "worker",
                "revision": "sha256-" + digest.hexdigest(),
                "models": [m.id for m in group],
                "weights": [],
                "weightless": True,
                "secrets": [],
            }
        )
    return {"schema_version": 1, "provider": "modal-example", "targets": targets}
