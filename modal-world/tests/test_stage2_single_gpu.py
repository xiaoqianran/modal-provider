from pathlib import Path

from modal_world.stage2_patch import patch_stage2_single_gpu


def test_stage2_uses_single_process_and_persistent_cuda_caches():
    source = Path("modal_world/app.py").read_text()
    start = source.index('def worldgen_case000_stage2(job_id: str = "case000")')
    end = source.index("\n\n@app.function(", start)
    section = source[start:end]
    assert '"torch.distributed.run"' not in section
    assert '"traj_render.py"' in section
    assert "CUDA_CACHE_PATH" in section
    assert "TORCH_EXTENSIONS_DIR" in section
    assert "TORCHINDUCTOR_CACHE_DIR" in section
    assert "TRITON_CACHE_DIR" in section
    assert section.count("model_cache.commit()") >= 2


def test_stage2_patch_matches_pinned_upstream(tmp_path: Path):
    src = Path("/tmp/hyworld2-src")
    if not src.exists():
        return
    target = tmp_path / "source"
    target.mkdir()
    for rel in (
        "hyworld2/worldgen/traj_render.py",
        "hyworld2/worldgen/src/pointcloud.py",
    ):
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text((src / rel).read_text())
    patch_stage2_single_gpu(target)
    traj = (target / "hyworld2/worldgen/traj_render.py").read_text()
    pcd = (target / "hyworld2/worldgen/src/pointcloud.py").read_text()
    assert "if world_size > 1:" in traj
    assert traj.count("if world_size > 1:") >= 5
    assert "if device_num == 1:" in pcd
    assert "return pcd_renders, pcd_mask" in pcd


def test_stage4_resume_allows_missing_sky_points():
    source = Path("modal_world/app.py").read_text()
    start = source.index('def worldgen_case000_stage4(job_id: str = "case000")')
    end = source.index("\n\n@app.function(", start)
    section = source[start:end]
    assert "sky_points_path.stat().st_size if sky_points_path.is_file() else 0" in section
