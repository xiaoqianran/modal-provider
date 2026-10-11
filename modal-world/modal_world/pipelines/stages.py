"""World pipeline topology; no GPU stage imports at discovery time."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..deployment import deployment_manifest


@dataclass(frozen=True, slots=True)
class Stage:
    app: str
    module: str
    kind: str
    models: tuple[str, ...]


def list_stages() -> tuple[Stage, ...]:
    """Derive stages from the existing deploy manifest without changing App IDs."""
    return tuple(
        Stage(
            app=target["app"],
            module=target["module"],
            kind=target["kind"],
            models=tuple(target.get("models", ())),
        )
        for target in deployment_manifest()["targets"]
    )


def validate_stage_modules(root: Path | None = None) -> tuple[str, ...]:
    root = root or Path(__file__).resolve().parents[1]
    errors: list[str] = []
    apps: set[str] = set()
    for stage in list_stages():
        if stage.app in apps:
            errors.append(f"duplicate World App: {stage.app}")
        apps.add(stage.app)
        if not stage.module.startswith("modal_world."):
            errors.append(f"invalid stage module: {stage.module}")
            continue
        source = root.joinpath(*stage.module.split(".")[1:]).with_suffix(".py")
        if not source.is_file():
            errors.append(f"missing stage module: {stage.module}")
    return tuple(errors)
