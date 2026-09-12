"""Explicit FIRE3D entry point sharing only the lightweight World contract."""

from pathlib import Path
from typing import Any

from modal_world.contracts import Operation, WorldRequest, WorldResult

from .backend import Fire3DBackend


def execute(
    *,
    input_path: str,
    output_dir: str,
    operation: str = "reconstruct",
    options: dict[str, Any] | None = None,
) -> WorldResult:
    return Fire3DBackend().run(
        WorldRequest(
            operation=Operation(operation),
            input_path=Path(input_path),
            output_dir=Path(output_dir),
            options=options or {},
        )
    )
