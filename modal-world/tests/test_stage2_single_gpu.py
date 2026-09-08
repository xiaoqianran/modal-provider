from pathlib import Path

from modal_world.stage2_patch import patch_stage2_single_gpu


def test_stage2_pipeline_uses_persistent_worker_and_runtime_cache_without_cpu_proxy():
    app_source = Path("modal_world/app.py").read_text()
    pipeline = app_source[app_source.index("def worldgen_pipeline("):]
    assert 'def worldgen_case000_stage2(' not in app_source
    assert 'modal.Cls.from_name("modal-world-stage2", "WorldNavRenderer")' in app_source
    assert '"torch.distributed.run"' not in pipeline
    assert '"traj_render.py"' not in pipeline
    assert "_spawn_worker_call(\n        worldnav_worker.render" in pipeline

    worker = Path("modal_world/stage2_app.py").read_text()
    assert 'app = modal.App("modal-world-stage2")' in worker
    assert "min_containers=0" in worker
    assert "scaledown_window=5 * 60" in worker
    assert "@modal.enter()" in worker
    assert "worldgen_outputs.reload()" in worker
    assert "@modal.method()" in worker
    assert "def render" in worker
    assert "point_rendering(" in worker
    assert "device_num=1" in worker
    assert '"hyworld2-runtime-cache-v2", create_if_missing=True, version=2' in worker
    assert "model_cache.with_mount_options(read_only=True)" in worker
    for key in (
        "CUDA_CACHE_PATH",
        "TORCH_EXTENSIONS_DIR",
        "TORCHINDUCTOR_CACHE_DIR",
        "TRITON_CACHE_DIR",
    ):
        assert key in worker
    assert "runtime_cache.commit()" in worker
    assert "model_cache.commit()" not in worker


def test_stage2_patch_matches_pinned_upstream(tmp_path: Path):
    src = Path("/tmp/hyworld2-src")
    if not (
        (src / "hyworld2/worldgen/traj_render.py").is_file()
        and (src / "hyworld2/worldgen/src/pointcloud.py").is_file()
    ):
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
    source = Path("modal_world/stage45_core.py").read_text()
    start = source.index("def run_stage4_core(")
    end = source.index("def run_stage5_core(", start)
    section = source[start:end]
    assert "sky_points_path.stat().st_size if sky_points_path.is_file() else 0" in section
