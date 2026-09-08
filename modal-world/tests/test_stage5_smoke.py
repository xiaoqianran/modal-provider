from pathlib import Path


def _smoke_core() -> str:
    source = Path("modal_world/stage45_core.py").read_text()
    return source[source.index("def run_stage5_smoke_core(") :]


def test_stage5_smoke_is_short_real_and_non_destructive():
    section = _smoke_core()
    assert "steps = 100" in section
    assert 'result_dir = target / "gs_smoke_result"' in section
    assert '"--disable_viewer"' in section
    assert '"--save_ply"' in section
    assert '"--convert_to_spz"' in section
    assert '"--depth_loss"' in section
    assert '"--normal_loss"' in section
    assert '"--export_mesh"' not in section
    assert "not checkpoints or not plys or not spzs" in section


def test_stage5_smoke_uses_job_isolated_worldgen_root():
    section = _smoke_core()
    assert "target = resolve_worldgen_job_root(job_id)" in section
    assert 'Path("/worldgen/case000")' not in section
    assert 'result_dir = target / "gs_smoke_result"' in section


def test_stage5_smoke_reuses_persistent_runtime_cache_and_requires_preloaded_vgg():
    app = Path("modal_world/app.py").read_text()
    signature = 'def worldgen_case000_stage5_smoke(job_id: str = "case000")'
    start = app.rfind("@app.function(", 0, app.index(signature))
    end = app.index("\n\n\n@app.function(", app.index(signature))
    wrapper = app[start:end]
    assert '"/runtime-cache": runtime_cache' in wrapper
    assert "model_cache.with_mount_options(read_only=True)" in wrapper
    assert "worldgen_outputs.reload()" in wrapper
    assert "run_stage5_smoke_core(" in wrapper
    core = _smoke_core()
    assert "TORCH_EXTENSIONS_DIR" in core
    assert "TORCHINDUCTOR_CACHE_DIR" in core
    assert "TRITON_CACHE_DIR" in core
    assert "vgg16-397923af.pth" in core
    assert "Stage 5 VGG16 cache missing" in core
