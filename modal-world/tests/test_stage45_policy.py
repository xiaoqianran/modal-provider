from pathlib import Path


def _stage45_function() -> str:
    source = Path("modal_world/stage45_app.py").read_text()
    start = source.index("def worldgen_case000_stage45_rtx6000(")
    return source[start : source.index("\n\n@app.function", start)]


def test_stage45_uses_existing_rtx_stage5_image_and_resources():
    source = Path("modal_world/stage45_app.py").read_text()
    assert 'app = modal.App("modal-world-stage45")' in source
    assert "image=hyworld2_worldgen_stage5_image" in source
    assert "gpu=GPU" in source
    assert "cpu=16.0" in source
    assert "memory=65536" in source
    assert "timeout=3 * 60 * 60" in source
    assert '"hyworld2-runtime-cache-v2", create_if_missing=True, version=2' in source


def test_stage45_runs_stage4_then_stage5_without_intermediate_reload():
    section = _stage45_function()
    reload_at = section.index("worldgen_outputs.reload()")
    stage4_at = section.index("stage4 = run_stage4_core(")
    stage5_at = section.index("stage5 = run_stage5_core(")
    assert reload_at < stage4_at < stage5_at
    assert "worldgen_outputs.reload()" not in section[stage4_at:stage5_at]
    stage4_call = section[stage4_at : section.index("stage4_wall_s", stage4_at)]
    assert "commit_worldgen=None" in stage4_call
    assert "commit_failure_worldgen=worldgen_outputs.commit" in stage4_call
    assert "defer_stale_cleanup=True" in stage4_call
    assert "stale_cleanup = threading.Thread(" in section
    assert "stale_cleanup.join()" in section
    stage5_call = section[stage5_at : section.index("stage5_wall_s", stage5_at)]
    assert "commit_worldgen=None" in stage5_call
    assert "commit_failure_worldgen=worldgen_outputs.commit" in stage5_call
    assert "worldgen_outputs.commit()" in section


def test_stage45_preserves_profile_manifests_and_aggregate_timing():
    section = _stage45_function()
    assert 'stage_profile_file(target, "stage45", steps, ".log")' in section
    assert 'stage_profile_file(target, "stage45", steps, "_timing.json")' in section
    assert 'stage45_stage = stage_profile_name("stage45", steps)' in section
    assert 'stage5_stage = stage_profile_name("stage5", steps)' in section
    assert 'stage_manifest_path(target, "stage4")' in section
    assert "stage_manifest_path(target, stage5_stage)" in section
    assert "stage=stage45_stage" in section
    assert "write_stage_manifest(target, stage45_stage, manifest)" in section
    for key in ("stage4_s", "stage5_s", "stage45_s", "gpu_peak_used_mib"):
        assert f'"{key}"' in section


def test_stage45_core_parameterizes_terminal_outputs_and_steps():
    source = Path("modal_world/stage45_core.py").read_text()
    stage5 = source[source.index("def run_stage5_core(") :]
    assert "steps: int = 8000" in stage5
    assert "stage5_artifacts(target, steps)" in stage5
    assert "stage5_result_dir(target, steps)" in stage5
    assert '"--max_steps"' in stage5
    assert '"--ply_steps"' in stage5
    assert "str(steps)" in stage5
    assert '"export_mesh": bool(export_mesh)' in stage5


def test_stage45_checks_stage5_static_cache_before_stage4():
    section = _stage45_function()
    assert section.index("assert_stage5_static_cache()") < section.index(
        "stage4 = run_stage4_core("
    )


def test_stage45_force_reaches_both_stage4_and_stage5():
    section = _stage45_function()
    stage4_call = section[
        section.index("stage4 = run_stage4_core(") : section.index("stage4_wall_s")
    ]
    stage5_call = section[
        section.index("stage5 = run_stage5_core(") : section.index("stage5_wall_s")
    ]
    assert "force=bool(force)" in stage4_call
    assert "force=bool(force)" in stage5_call


def test_stage45_smoke_reuses_stage4_and_writes_only_smoke_result():
    source = Path("modal_world/stage45_app.py").read_text()
    start = source.index('def worldgen_case000_stage45_smoke(job_id: str = "case000")')
    section = source[start:]
    assert "stage4 = run_stage4_core(" in section
    assert "stage5 = run_stage5_smoke_core(" in section
    assert section.index("stage4 = run_stage4_core(") < section.index(
        "stage5 = run_stage5_smoke_core("
    )
    assert 'target / "stage45_smoke_timing.json"' in section
    stage4_call = section[
        section.index("stage4 = run_stage4_core(") : section.index("stage4_wall_s")
    ]
    assert "commit_worldgen=None" in stage4_call
    assert "commit_failure_worldgen=worldgen_outputs.commit" in stage4_call
    assert "commit_worldgen=worldgen_outputs.commit" in section[
        section.index("stage5 = run_stage5_smoke_core(") :
    ]
    smoke_core = Path("modal_world/stage45_core.py").read_text()
    smoke_core = smoke_core[smoke_core.index("def run_stage5_smoke_core(") :]
    assert 'result_dir = target / "gs_smoke_result"' in smoke_core
    assert 'result_dir = target / "gs_result"' not in smoke_core
