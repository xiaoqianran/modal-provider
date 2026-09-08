from pathlib import Path


def test_pipeline_uses_stage45_by_default_and_preserves_legacy_fallback():
    source = Path("modal_world/app.py").read_text()
    start = source.index("def worldgen_pipeline(")
    section = source[start:]
    assert "worldnav_worker = _worldnav_worker()" in section
    assert "worldnav_worker.generate_nav" in section
    assert "worldnav_worker.render" in section
    assert "_worldstereo_worker().generate" in section
    assert "merge_stage45: bool = True" in section
    assert "steps: int = 8000" in section
    assert "if merge_stage45:" in section
    assert 'stages["stage45"] = _stage45_worker().remote' in section
    assert "worldgen_case000_stage4.remote" in section
    assert "worldgen_case000_stage5.remote" in section
    assert '"modal-world-stage45", "worldgen_case000_stage45_rtx6000"' in source
    for stage in (1, 2, 3):
        assert f"def worldgen_case000_stage{stage}(" not in source
    assert "worldgen_garden_stage0.remote" in section
    assert '"modal-world-runtime-compile", "compile_world_runtime"' in section
    assert ").remote(job_id=job_id, force=bool(force), steps=steps)" in section
    assert "runtime_dir = runtime_result_dir(target, steps)" in section
    assert 'runtime_dir / "environment.ply"' in section
    assert 'runtime_dir / "semantics.json"' in section
    assert "stage5_artifacts(target, steps).spz" in section
    assert 'navigation_path.is_file()' in section
    assert 'role="world-mesh"' in section
    assert 'role="world-semantics"' in section
    assert 'role="world-visual"' in section


def test_pipeline_force_propagates_across_every_generation_stage():
    source = Path("modal_world/app.py").read_text()
    section = source[source.index("def worldgen_pipeline(") :]
    assert "force=bool(force)" in section[section.index("worldgen_garden_stage0.remote") :]
    assert section.count("force=bool(force)") >= 7
    helper = source[source.index("def _spawn_worker_call") : source.index("def _worldnav_worker")]
    assert ".spawn(job_id=job_id, force=bool(force))" in helper


def test_pipeline_rejects_invalid_steps_before_any_remote_work():
    source = Path("modal_world/app.py").read_text()
    section = source[source.index("def worldgen_pipeline(") :]
    validate = section.index('raise ValueError("steps must be > 0")')
    static_cache = section.index('ensure_stage5_static_cache.remote()')
    stage0 = section.index("worldgen_garden_stage0.remote(")
    assert validate < static_cache < stage0


def test_stage0_prompt_is_runtime_input_not_hardcoded_only():
    source = Path("modal_world/app.py").read_text()
    start = source.index("def worldgen_garden_stage0(")
    end = source.index("def _spawn_worker_call", start)
    section = source[start:end]
    assert "prompt: str = GARDEN_PANO_PROMPT" in section
    assert '"prompt": prompt' in section
    assert "prompt=prompt" in section
