from pathlib import Path


def test_stage5_preflight_uses_official_dataset_and_lpips_cache():
    source = Path("modal_world/app.py").read_text()
    start = source.index('def preflight_worldgen_case000_stage5(job_id: str = "case000")')
    section = source[start:]
    assert "downsample_pts_num=1_000_000" in section
    assert 'downsample_mode="geometry_aware"' in section
    assert 'LearnedPerceptualImagePatchSimilarity(net_type="vgg"' in section
    assert "TORCH_HOME" in section


def test_stage5_preflight_uses_requested_job_and_commits_vgg_cache():
    source = Path("modal_world/app.py").read_text()
    start = source.index('def preflight_worldgen_case000_stage5(job_id: str = "case000")')
    section = source[start : source.index("def worldgen_case000_stage5_smoke", start)]
    assert "target = resolve_worldgen_job_root(job_id)" in section
    assert 'data_dir = target / "gs_data"' in section
    assert "vgg16-397923af.pth" in section
    assert "model_cache.commit()" in section


def test_stage5_full_uses_documented_single_gpu_steps_and_exports_mesh():
    source = Path("modal_world/app.py").read_text()
    start = source.index(
        'def worldgen_case000_stage5(job_id: str = "case000", force: bool = False)'
    )
    end = source.index("def worldgen_case000_stage5_smoke", start)
    section = source[start:end]
    assert "steps = 8000" in section
    assert 'result_dir = target / "gs_result"' in section
    assert '"--export_mesh"' in section
    assert '"--convert_to_spz"' in section
    assert 'result_dir / "ply" / "fuse_post.ply"' in section
    assert 'stage="stage5"' in section
    assert 'manifest_matches(target, "stage5", manifest)' in section


def test_stage5_full_can_adopt_only_the_known_terminal_barrier_failure():
    source = Path("modal_world/app.py").read_text()
    start = source.index(
        'def worldgen_case000_stage5(job_id: str = "case000", force: bool = False)'
    )
    end = source.index("def worldgen_case000_stage5_smoke", start)
    section = source[start:end]
    assert "outputs_complete = all(" in section
    assert "st_mtime_ns" in section
    assert 'prior_timing.get("steps") == steps' in section
    assert 'prior_timing.get("returncode") == 1' in section
    assert "UnboundLocalError: cannot access local variable 'dist'" in section
    assert 'prior_timing["adopted_terminal_barrier_failure"] = True' in section
    assert 'write_stage_manifest(target, "stage5", manifest)' in section
