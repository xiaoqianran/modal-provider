"""Build-only cloud preflight for migrated worker source and image patch inputs.

This intentionally does NOT deploy Modal Apps or start GPU functions.
"""
from __future__ import annotations

from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
CHECK = (
    "from pathlib import Path; import py_compile; "
    "p=Path('/opt/modal_3d'); "
    "w=['fastsam3d','hunyuan21','trellis2','pixal3d','p3sam','xpart']; "
    "patches=['fastsam3d','hunyuan_paint_profile','p3sam','xpart']; "
    "assert all((p/'workers'/f'{n}.py').is_file() for n in w); "
    "assert all((p/'patches'/f'{n}.patch').is_file() for n in patches); "
    "[py_compile.compile(str(p/'workers'/f'{n}.py'),doraise=True) for n in w]; "
    "print('Modal cloud image preflight passed: 6 workers, 4 patches')"
)


def main() -> None:
    image = (
        modal.Image.debian_slim(python_version="3.11")
        .add_local_dir(
            ROOT / "modal_3d", "/opt/modal_3d", copy=True,
            ignore=["**/__pycache__/**", "**/*.pyc", "texture_glb.py"],
        )
        .run_commands(f"python -c {CHECK!r}")
    )
    app = modal.App.lookup("modal-3d-image-preflight", create_if_missing=True)
    with modal.enable_output():
        image.build(app)
    print(f"IMAGE_BUILD_OK {image.object_id}")


if __name__ == "__main__":
    main()
