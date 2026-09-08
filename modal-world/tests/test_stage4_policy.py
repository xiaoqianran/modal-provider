from pathlib import Path


def _stage4_core() -> str:
    source = Path("modal_world/stage45_core.py").read_text()
    start = source.index("def run_stage4_core(")
    end = source.index("def run_stage5_core(", start)
    return source[start:end]


def test_stage4_uses_official_quality_flags_and_true_single_process():
    section = _stage4_core()
    assert '"torch.distributed.run"' not in section
    assert '"--nproc_per_node=1"' not in section
    assert '"gen_gs_data.py"' in section
    assert '"--save_normal"' in section
    assert '"--split_sky"' in section
    assert '"--split_align"' not in section
    assert 'env["WORLD_SIZE"] = "1"' in section


def test_stage4_runtime_patch_is_image_build_time_and_offline():
    runtime = Path("modal_world/hyworld2_runtime.py").read_text()
    patch = Path("modal_world/stage4_patch.py").read_text()
    assert ".run_function(patch_stage4_single_gpu" in runtime
    assert "local_files_only=True" in patch
    assert "if world_size == 1:" in patch
    assert "if world_size > 1:" in patch
    assert "dist.is_initialized()" in patch
    assert "MoGeModel.from_pretrained" not in _stage4_core()


def test_stage4_gpu_subprocess_sampler_is_opt_in():
    section = _stage4_core()
    assert 'os.environ.get("MODAL_WORLD_DEBUG_GPU_SAMPLER") == "1"' in section
    assert '"gpu_sampler_enabled": monitor is not None' in section


def test_legacy_stage4_entrypoint_remains_h100_wrapper():
    app = Path("modal_world/app.py").read_text()
    start = app.index('@app.function(\n    image=hyworld2_worldgen_stage2_h100_image')
    end = app.index("\n\n@app.function(", start)
    section = app[start:end]
    assert "gpu=H100_GPU" in section
    assert 'def worldgen_case000_stage4(job_id: str = "case000", force: bool = False)' in section
    assert "run_stage4_core(" in section
    assert "force=bool(force)" in section


def test_stage4_patch_preserves_upstream_per_frame_moge_pipeline():
    patch = Path("modal_world/stage4_patch.py").read_text()
    assert "infer_normals_batched" not in patch
    assert "HYWORLD_STAGE4_MOGE_BATCH" not in patch
    assert "local_files_only=True" in patch


def test_stage4_resume_and_force_validate_complete_dataset_and_inputs():
    section = _stage4_core()
    assert "force: bool = False" in section
    assert "if not force and cameras_path.is_file()" in section
    assert 'meta_info_path = gs_data / "meta_info.json"' in section
    assert "shutil.rmtree(gs_data)" not in section
    assert '"--custom_out_name"' in section
    assert "build_data.rename(gs_data)" in section
    assert "gs_data.rename(stale_data)" in section
    assert "defer_stale_cleanup: bool = False" in section
    assert 'worldstereo-memory-dmd_result.mp4' in section
    assert 'generation_bank.glob("*/*/depths/*.png")' in section
    assert 'target / "panorama.png"' in section
    assert "_commit(commit_worldgen)" in section


def test_stage4_quality_contract_remains_full_density():
    section = _stage4_core()
    assert '"--save_normal"' in section
    assert '"--split_sky"' in section
    assert '"--interval"' not in section
    assert '"--no_aerial"' not in section
