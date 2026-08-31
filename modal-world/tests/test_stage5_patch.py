from pathlib import Path

import pytest

from modal_world.stage5_patch import patch_stage5_single_gpu


def _trainer_path(root: Path) -> Path:
    path = root / "hyworld2/worldgen/world_gs_trainer.py"
    path.parent.mkdir(parents=True)
    return path


def test_stage5_single_gpu_patch_guards_unique_mesh_export_barrier(tmp_path: Path):
    trainer = _trainer_path(tmp_path)
    trainer.write_text("before\n                    dist.barrier()\nafter\n")

    patch_stage5_single_gpu(tmp_path)

    source = trainer.read_text()
    lines = source.splitlines()
    assert "                    if world_size > 1:\n" in source
    assert "                        dist.barrier()" in lines
    assert "                    dist.barrier()" not in lines


def test_stage5_single_gpu_patch_rejects_unpinned_barrier_shape(tmp_path: Path):
    trainer = _trainer_path(tmp_path)
    trainer.write_text("dist.barrier()\n")

    with pytest.raises(RuntimeError, match="unique pinned Stage 5 mesh-export barrier"):
        patch_stage5_single_gpu(tmp_path)


def test_stage5_patch_is_applied_at_image_build_time():
    runtime = Path("modal_world/hyworld2_runtime.py").read_text()
    assert "from .stage5_patch import patch_stage5_single_gpu" in runtime
    assert ".run_function(patch_stage5_single_gpu, args=(HYWORLD2_SOURCE,))" in runtime
