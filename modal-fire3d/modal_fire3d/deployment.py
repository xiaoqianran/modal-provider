"""FIRE3D deployment metadata; importing it does not load either GPU runtime."""

import hashlib
from pathlib import Path

from modal_world import backend, contracts


def runtime_revision() -> str:
    root = Path(__file__).resolve().parent
    sources = {path.relative_to(root).as_posix(): path for path in root.rglob("*.py")}
    # Only these two shared modules are part of the FIRE3D execution contract.
    sources.update({
        "shared/backend.py": Path(backend.__file__),
        "shared/contracts.py": Path(contracts.__file__),
    })
    digest = hashlib.sha256()
    for name, path in sorted(sources.items()):
        digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    return f"sha256-{digest.hexdigest()[:32]}"


def deployment_manifest() -> dict[str, object]:
    prerequisites = []
    for component in ("flash_attn", "pytorch3d"):
        artifact_name = component.replace("_", "-")
        tag = f"fire3d-{artifact_name}-py310-cu128-torch271-sm90-v1"
        module = f"integrations.fire3d.build.fire3d_{component}_sm90"
        prerequisites.append({
            "volume": "modal-build-artifacts",
            "requiredPaths": [f"{tag}/manifest.json"],
            "prepare": [
                {"module": module, "function": "build"},
                {"module": module, "function": "smoke"},
            ],
        })
    return {
        "provider": "modal-fire3d",
        "targets": [{
            "app": "modal-world-fire3d",
            "module": "modal_fire3d.app",
            "kind": "reconstruction",
            "revision": runtime_revision(),
            "models": ["fire3d"],
            "secrets": [],
            "required": True,
            "prerequisites": prerequisites,
        }],
    }
