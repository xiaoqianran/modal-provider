"""Offline preflight for Modal workers: imports, bundled patches, and wheel contents."""
from __future__ import annotations

import importlib
import zipfile
from pathlib import Path

import pytest

WORKERS = ("fastsam3d", "hunyuan21", "trellis2", "pixal3d", "p3sam", "xpart")
PATCHES = {"fastsam3d": "fastsam3d.patch", "hunyuan21": "hunyuan_paint_profile.patch", "p3sam": "p3sam.patch", "xpart": "xpart.patch"}


@pytest.mark.parametrize("name", WORKERS)
def test_migrated_worker_imports_and_has_modal_app(name: str) -> None:
    module = importlib.import_module(f"modal_3d.workers.{name}")
    assert module.app is not None
    assert Path(module.__file__).parent.name == "workers"


@pytest.mark.parametrize("name,filename", PATCHES.items())
def test_migrated_worker_patch_resolves(name: str, filename: str) -> None:
    module = importlib.import_module(f"modal_3d.workers.{name}")
    patch = getattr(module, "PAINT_PROFILE_PATCH" if name == "hunyuan21" else "PATCH")
    assert patch.is_file(), f"{name} missing local image build patch: {patch}"
    assert patch.name == filename
    assert patch.parent == Path(module.__file__).resolve().parents[1] / "patches"


def test_built_wheel_contains_workers_and_patches(tmp_path: Path) -> None:
    import subprocess

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(root)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
    for worker in WORKERS:
        assert f"modal_3d/workers/{worker}.py" in names
    for patch in PATCHES.values():
        assert f"modal_3d/patches/{patch}" in names
