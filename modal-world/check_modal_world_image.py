"""Build a minimal CPU-only image to verify World pipeline source packaging.

No production worker image, deployment, or GPU function is started.
"""
from __future__ import annotations

from pathlib import Path

import modal

PACKAGE = Path(__file__).resolve().parent / "modal_world"
CHECK = (
    "from pathlib import Path; import ast; "
    "p=Path('/opt/modal_world'); "
    "names=['app','stage2_app','stage3_app','stage45_app','runtime_compile_app']; "
    "parts=['stages','orchestrator','checkpoints','resume','artifacts']; "
    "files=[p/(n+'.py') for n in names]+[p/'pipelines'/(n+'.py') for n in parts]; "
    "assert all(f.is_file() for f in files), [str(f) for f in files if not f.is_file()]; "
    "[ast.parse(f.read_text(encoding='utf-8'),filename=str(f)) for f in files]; "
    "print('WORLD_IMAGE_SOURCE_OK: 5 entrypoints, 5 pipeline modules')"
)


def main() -> None:
    image = (
        modal.Image.debian_slim(python_version="3.11")
        .add_local_dir(PACKAGE, "/opt/modal_world", copy=True, ignore=["**/__pycache__/**", "**/*.pyc"])
        .run_commands(f"python -c {CHECK!r}")
    )
    app = modal.App.lookup("modal-world-source-preflight", create_if_missing=True)
    with modal.enable_output():
        image.build(app)
    print(f"WORLD_IMAGE_BUILD_OK {image.object_id}")


if __name__ == "__main__":
    main()

