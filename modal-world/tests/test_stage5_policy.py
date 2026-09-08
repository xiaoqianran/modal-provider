from pathlib import Path


def _stage5_core() -> str:
    source = Path("modal_world/stage45_core.py").read_text()
    return source[source.index("def run_stage5_core(") :]


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


def test_stage5_full_uses_parameterized_single_gpu_steps_and_exports_mesh():
    section = _stage5_core()
    assert "steps: int = 8000" in section
    assert "result_dir = stage5_result_dir(target, steps)" in section
    assert 'stage5_stage = stage_profile_name("stage5", steps)' in section
    assert 'command.append("--export_mesh")' in section
    assert '"--convert_to_spz"' in section
    assert "stage5_artifacts(target, steps)" in section
    assert "stage=stage5_stage" in section
    assert "manifest_matches(target, stage5_stage, manifest)" in section
    assert '"steps": steps' in section
    assert 'directory.glob("*.png")' in section


def test_stage5_full_can_adopt_only_the_known_terminal_barrier_failure():
    section = _stage5_core()
    assert "outputs_complete = all(" in section
    assert "st_mtime_ns" in section
    assert 'prior_timing.get("steps") == steps' in section
    assert 'prior_timing.get("returncode") == 1' in section
    assert "UnboundLocalError: cannot access local variable 'dist'" in section
    assert 'prior_timing["adopted_terminal_barrier_failure"] = True' in section
    assert "write_stage_manifest(target, stage5_stage, manifest)" in section
    assert "export_mesh" in section
    assert "commit_failure_worldgen" in section


def test_legacy_stage5_entrypoint_remains_rtx_wrapper():
    app = Path("modal_world/app.py").read_text()
    signature = "def worldgen_case000_stage5("
    start = app.rfind("@app.function(", 0, app.index(signature))
    end = app.index("\n\n@app.function(", app.index(signature))
    section = app[start:end]
    assert "image=hyworld2_worldgen_stage5_image" in section
    assert "gpu=GPU" in section
    assert "steps: int = 8000" in section
    assert "worldgen_outputs.reload()" in section
    assert "run_stage5_core(" in section


def test_stage5_patch_throttles_observability_without_touching_training_flags():
    patch = Path("modal_world/stage5_patch.py").read_text()
    assert "def _throttle_progress_description" in patch
    assert "if step % {int(every)} == 0 or step == max_steps - 1" in patch
    assert "pbar.set_description(desc)" in patch
    section = _stage5_core()
    for flag in (
        '"--use_scale_regularization"',
        '"--depth_loss"',
        '"--normal_loss"',
        '"--use_mask_gaussian"',
        '"--antialiased"',
    ):
        assert flag in section


def test_stage5_gpu_sampler_is_opt_in_for_production_training():
    section = _stage5_core()
    section = section[: section.index("def run_stage5_smoke_core(")]
    assert 'os.environ.get("MODAL_WORLD_DEBUG_GPU_SAMPLER") == "1"' in section
    assert '"gpu_sampler_enabled": monitor is not None' in section
    assert '"gpu_peak_used_mib": gpu_peak_mib if monitor is not None else None' in section


def test_stage5_image_branches_before_stage3_runtime_patch():
    runtime = Path("modal_world/hyworld2_runtime.py").read_text()
    start = runtime.index("hyworld2_worldgen_stage5_image = (")
    end = runtime.index("\n\n# Stage5 H100 profile", start)
    section = runtime[start:end]
    assert "hyworld2_worldgen_stage1_image.apt_install" in section
    assert "hyworld2_worldgen_stage3_image" not in section
    assert '"build-essential", "ninja-build"' in section
    assert '.pip_install("imagesize==1.4.1")' in section
    assert "patch_stage5_single_gpu" in section
    assert "patch_stage3_runtime" not in section


def test_stage5_static_cache_has_idempotent_cpu_bootstrap_and_pipeline_gate():
    source = Path("modal_world/app.py").read_text()
    start = source.index("def ensure_stage5_static_cache()")
    section = source[start : source.index("@app.function", start)]
    decorator = source[source.rfind("@app.function(", 0, start) : start]
    assert "gpu=" not in decorator
    assert 'volumes={"/models": model_cache}' in decorator
    assert "vgg16-397923af.pth" in section
    assert 'LearnedPerceptualImagePatchSimilarity(net_type="vgg"' in section
    assert "model_cache.commit()" in section
    pipeline = source[source.index("def worldgen_pipeline(") :]
    assert 'stages["stage5_static_cache"] = ensure_stage5_static_cache.remote()' in pipeline
