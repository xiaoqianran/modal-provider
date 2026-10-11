"""Worker discovery without importing GPU model modules.

Keep the existing Modal entrypoint modules stable while the worker layout evolves.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ..deployment import deployment_manifest


@dataclass(frozen=True, slots=True)
class WorkerEntry:
    app: str
    module: str
    kind: str
    models: tuple[str, ...]


def list_workers() -> tuple[WorkerEntry, ...]:
    """Derive the inventory from the deployment manifest (no duplicate registry)."""
    return tuple(
        WorkerEntry(
            app=target["app"],
            module=target["module"],
            kind=target["kind"],
            models=tuple(target.get("models", ())),
        )
        for target in deployment_manifest()["targets"]
    )


def validate_worker_modules(package_root: Path | None = None) -> tuple[str, ...]:
    """Check deployable modules exist and declare a matching Modal App, statically."""
    root = package_root or Path(__file__).resolve().parents[1]
    errors: list[str] = []
    seen_apps: set[str] = set()
    for worker in list_workers():
        if worker.app in seen_apps:
            errors.append(f"duplicate Modal app: {worker.app}")
        seen_apps.add(worker.app)
        if not worker.module.startswith("modal_3d."):
            errors.append(f"invalid worker module: {worker.module}")
            continue
        rel = Path(*worker.module.split(".")[1:]).with_suffix(".py")
        source = root / rel
        if not source.is_file():
            errors.append(f"missing worker module: {worker.module}")
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        if not any(isinstance(node, (ast.Assign, ast.AnnAssign)) and (
            any(isinstance(t, ast.Name) and t.id == "app" for t in node.targets)
            if isinstance(node, ast.Assign) else isinstance(node.target, ast.Name) and node.target.id == "app"
        ) for node in tree.body):
            errors.append(f"worker module has no app binding: {worker.module}")
    return tuple(errors)
