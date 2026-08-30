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
