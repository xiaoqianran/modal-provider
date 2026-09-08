from pathlib import Path

from modal_world.stage3_patch import patch_stage3_runtime


def test_stage3_runtime_patch_matches_pinned_upstream(tmp_path: Path):
    src = Path("/tmp/hyworld2-src")
    if not (
        (src / "hyworld2/worldgen/models/worldstereo_wrapper.py").is_file()
        and (src / "hyworld2/worldgen/src/retrieval_wm.py").is_file()
    ):
        return
    target = tmp_path / "source"
    for rel in (
        "hyworld2/worldgen/models/worldstereo_wrapper.py",
        "hyworld2/worldgen/src/retrieval_wm.py",
    ):
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text((src / rel).read_text())
    patch_stage3_runtime(target)
    wrapper = (target / "hyworld2/worldgen/models/worldstereo_wrapper.py").read_text()
    retrieval = (target / "hyworld2/worldgen/src/retrieval_wm.py").read_text()
    assert "T5TokenizerFast.from_pretrained" in wrapper
    assert "local_files_only=local_files_only" in wrapper
    assert "model_path, use_fast=True, local_files_only=True" in retrieval
    assert "model_path, local_files_only=True" in retrieval


def test_stage3_worker_is_persistent_and_worldstereo_is_lazy():
    source = Path("modal_world/stage3_app.py").read_text()
    assert 'app = modal.App("modal-world-stage3")' in source
    assert "min_containers=0" in source
    assert "scaledown_window=5 * 60" in source
    assert "max_containers=1" in source
    assert "model_cache.with_mount_options(read_only=True)" in source
    assert '"hyworld2-runtime-cache-v2", create_if_missing=True, version=2' in source
    assert "@modal.enter()" in source
    assert "def load_models" in source
    assert "WorldStereo.from_pretrained" in source
    assert "@modal.method()" in source
    assert "def generate" in source
    enter = source[source.index("def load_models") : source.index("def _load_worldstereo")]
    assert "self.worldstereo = None" in enter
    assert "self._load_worldstereo()" not in enter
    generate = source[source.index("def generate") :]
    assert "WorldStereo.from_pretrained" not in generate
    assert "Sam3VideoModel.from_pretrained" not in generate
    assert "MoGeModel.from_pretrained" not in generate
    resume_check = generate.index("not recompute_downstream")
    lazy_load = generate.index("if self.worldstereo is None:")
    assert resume_check < lazy_load
    assert generate.index("started = time.perf_counter()") < lazy_load
    assert generate.index("torch.cuda.reset_peak_memory_stats()") < lazy_load
    assert '"worldstereo_load_call_s"' in generate


def test_stage3_probe_explicitly_loads_worldstereo():
    source = Path("modal_world/stage3_app.py").read_text()
    probe = source[source.index("def probe") : source.index("def _stage3_manifest")]
    assert "self._load_worldstereo()" in probe
    assert '"worldstereo_load_s"' in probe


def test_stage3_force_rebuilds_worldmirror_without_stale_images():
    source = Path("modal_world/stage3_app.py").read_text()
    generate = source[source.index("def generate") :]
    assert "if force and world_mirror_dir.exists():" in generate
    assert '"world_mirror_data"' in generate
    assert "world_mirror_dir.rename(stale_world_mirror)" in generate
    assert "stale_world_mirror.rename(world_mirror_dir)" in generate
    assert "memory_bank.apply_worldmirror(skip_exist=not force)" in generate


def test_stage3_patch_is_image_build_time_and_legacy_hot_patch_removed():
    runtime = Path("modal_world/hyworld2_runtime.py").read_text()
    app = Path("modal_world/app.py").read_text()
    assert ".run_function(patch_stage3_runtime" in runtime
    section = app[app.index("def worldgen_pipeline(") :]
    assert "patch_worldstereo_wrapper" not in section
    assert "retrieval_source.replace" not in section
    assert 'modal.Cls.from_name("modal-world-stage3", "WorldStereoWorker")' in app
    assert "_worldstereo_worker().generate" in section


def test_stage3_worker_preserves_upstream_worldgen_cwd():
    source = Path("modal_world/stage3_app.py").read_text()
    enter = source[source.index("def load_models") : source.index("def _stage3_manifest")]
    assert "os.chdir(worldgen_root)" in enter
    assert 'find_spec("worldrecon.pipeline")' in enter


def test_stage3_worker_skips_existing_trajectory_results_but_updates_memory():
    source = Path("modal_world/stage3_app.py").read_text()
    generate = source[source.index("def generate") :]
    assert "if not force and result_path.is_file():" in generate
    assert 'timer.track("[IO] Reload existing result for memory update")' in generate
    skip_block = generate[
        generate.index("if not force and result_path.is_file():") : generate.index(
            'with timer.track("Memory Retrieval")'
        )
    ]
    assert "memory_bank.update_memory" in skip_block
    assert "continue" in skip_block


def test_stage3_worker_adds_hyworld2_package_root_and_cpu_preflight():
    source = Path("modal_world/stage3_app.py").read_text()
    assert 'hyworld2_root = f"{HYWORLD2_SOURCE}/hyworld2"' in source
    assert 'f"{hyworld2_root}:{worldgen_root}:{HYWORLD2_SOURCE}"' in source
    assert "def verify_stage3_module_paths" in source
    preflight = source[source.index("def verify_stage3_module_paths") : source.index("@app.cls(")]
    assert 'find_spec("worldrecon.pipeline")' in preflight
    assert "os.chdir(worldgen_root)" in preflight


def test_stage3_alignment_has_phase_profiling_without_algorithm_changes():
    patch = Path("modal_world/stage3_patch.py").read_text()
    worker = Path("modal_world/stage3_app.py").read_text()
    for name in (
        "phase1_mapping",
        "phase2_preprocess_align",
        "phase3_sync_kb",
        "phase4_detect_kb_anomalies",
        "phase5_finalize_kb",
        "phase6_build_pointclouds",
        "phase6_5_sor",
        "phase7_save_sync",
    ):
        assert name in patch
    assert 'getattr(memory_bank, "alignment_profile", {})' in worker
    assert '"alignment_profile": alignment_profile' in worker


def test_stage3_phase2_has_subprofiling():
    patch = Path("modal_world/stage3_patch.py").read_text()
    worker = Path("modal_world/stage3_app.py").read_text()
    for name in ("tensor_prep", "moge_infer", "sam3_sky", "frame_align_total"):
        assert name in patch
    assert '"alignment_phase2_profile": alignment_phase2_profile' in worker


def test_stage3_phase2_frame_alignment_has_detail_profiling():
    patch = Path("modal_world/stage3_patch.py").read_text()
    worker = Path("modal_world/stage3_app.py").read_text()
    for name in ("frame_prep", "guided_depth", "percentile", "normal_mask", "ransac"):
        assert name in patch
    assert '"alignment_phase2_detail": alignment_phase2_detail' in worker
    assert 'alignment_phase2_detail["unattributed"]' in worker


def test_stage3_downstream_benchmark_bypasses_only_terminal_resume():
    source = Path("modal_world/stage3_app.py").read_text()
    assert "recompute_downstream: bool = False" in source
    resume_start = source.index("if (", source.index("def generate("))
    resume_end = source.index("if not render_list:", resume_start)
    resume = source[resume_start:resume_end]
    assert "not recompute_downstream" in resume
    loop = source[source.index("for render_path in render_list:") :]
    assert "if not force and result_path.is_file():" in loop
    assert "memory_bank.apply_worldmirror(skip_exist=not force)" in loop


def test_stage3_phase6_avoids_quadratic_concat_and_overlaps_depth_png_io():
    patch = Path("modal_world/stage3_patch.py").read_text()
    assert '"point_chunks": [], "color_chunks": []' in patch
    assert '["point_chunks"].append(update_points3d)' in patch
    assert "np.concatenate(point_chunks, axis=0)" in patch
    assert "np.concatenate(color_chunks, axis=0)" in patch
    assert "_depth_save_executor = ThreadPoolExecutor(max_workers=8)" in patch
    assert "_depth_save_executor.submit(" in patch
    assert "_depth_save_futures = collections.deque()" in patch
    assert "_depth_save_max_pending = 16" in patch
    assert "_depth_save_futures.popleft().result()" in patch
    assert "self.points.clone(), aligned_depth" in patch
    assert "self.points, aligned_depth" in patch


def test_stage3_percentile_ranking_stays_on_gpu():
    patch = Path("modal_world/stage3_patch.py").read_text()
    assert "def compute_depth_percentile_map_torch" in patch
    assert "torch.sort(valid_depths).values" in patch
    assert "torch.searchsorted(sorted_depths, valid_depths, right=True)" in patch
    assert "guided_depth_percentile_t" in patch
    assert "mono_depth_percentile_t" in patch
    assert "guided_mono_mask.float().sum()" in patch


def test_stage3_has_load_only_gpu_probe():
    source = Path("modal_world/stage3_app.py").read_text()
    probe = source[source.index("def probe") : source.index("def _stage3_manifest")]
    assert '"worldstereo_loaded"' in probe
    assert '"moge_loaded"' in probe
    assert '"sam3_loaded"' in probe
    assert "memory_allocated" in probe
    assert "def generate" not in probe


def test_stage3_reload_worldgen_volume_before_generate():
    source = Path("modal_world/stage3_app.py").read_text()
    generate = source[source.index("def generate") :]
    assert "worldgen_outputs.reload()" in generate[:300]


def test_stage3_checkpoints_completed_gpu_work_to_volume():
    source = Path("modal_world/stage3_app.py").read_text()
    start = source.index("def generate(")
    section = source[start:]
    assert 'MODAL_WORLD_STAGE3_CHECKPOINT_EVERY", "4"' in section
    assert "generated_since_commit += 1" in section
    assert "def commit_checkpoint()" in section
    assert "checkpoint_commit_s" in section
    assert "worldgen_outputs.commit()" in section
    assert "memory_bank.apply_worldmirror(skip_exist=not force)" in section
    apply_worldmirror = section.index("memory_bank.apply_worldmirror(skip_exist=not force)")
    alignment = section.index("memory_bank.alignment(debug_mode=False)")
    assert "commit_checkpoint()" in section[apply_worldmirror:alignment]
    assert '"checkpoint_commits": checkpoint_commits' in section
    assert '"checkpoint_commit_s": round(checkpoint_commit_s, 3)' in section
