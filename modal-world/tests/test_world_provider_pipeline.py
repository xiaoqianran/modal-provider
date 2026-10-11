from pathlib import Path


def test_pipeline_uses_stage45_by_default_and_preserves_legacy_fallback():
    source = Path("modal_world/app.py").read_text()
    start = source.index("def worldgen_pipeline(")
    section = source[start:]
    orchestrator = Path("modal_world/pipelines/orchestrator.py").read_text()
    assert "worldnav_worker = deps.worldnav_factory()" in orchestrator
    assert "worldnav_worker.generate_nav" in orchestrator
    assert "worldnav_worker.render" in orchestrator
    assert "deps.worldstereo_factory().generate" in orchestrator
    assert "merge_stage45: bool = True" in section
    assert "steps: int = 8000" in section
    assert "if merge_stage45:" in orchestrator
    assert 'stages["stage45"] = deps.stage45_factory().remote' in orchestrator
    assert "deps.stage4(" in orchestrator
    assert "deps.stage5(" in orchestrator
    assert '"modal-world-stage45", "worldgen_case000_stage45_rtx6000"' in source
    for stage in (1, 2, 3):
        assert f"def worldgen_case000_stage{stage}(" not in source
    assert "deps.stage0(" in orchestrator
    assert '"modal-world-runtime-compile", "compile_world_runtime"' in section
    assert "deps.runtime_compile(job_id=job_id, force=bool(force), steps=steps)" in orchestrator
    assert "artifacts = collect_world_artifacts(target, job_id, steps)" in section
    artifact_source = Path("modal_world/pipelines/artifacts.py").read_text()
    for expected in ('runtime_dir / "environment.ply"', 'runtime_dir / "semantics.json"', 'stage5_artifacts(target, steps).spz', 'navigation_path.is_file()', 'role="world-mesh"', 'role="world-semantics"', 'role="world-visual"'):
        assert expected in artifact_source



def test_pipeline_force_propagates_across_every_generation_stage():
    source = Path("modal_world/app.py").read_text()
    orchestrator = Path("modal_world/pipelines/orchestrator.py").read_text()
    assert orchestrator.count("force=bool(force)") >= 7
    helper = source[source.index("def _spawn_worker_call") : source.index("def _worldnav_worker")]
    assert ".spawn(job_id=job_id, force=bool(force))" in helper


def test_pipeline_rejects_invalid_steps_before_any_remote_work():
    source = Path("modal_world/app.py").read_text()
    section = source[source.index("def worldgen_pipeline(") :]
    validate = section.index('raise ValueError("steps must be > 0")')
    dispatch = section.index('stages = run_stages(')
    assert validate < dispatch
    orchestrator = Path('modal_world/pipelines/orchestrator.py').read_text()
    assert orchestrator.index('deps.ensure_static_cache()') < orchestrator.index('deps.stage0(')


def test_stage0_prompt_is_runtime_input_not_hardcoded_only():
    source = Path("modal_world/app.py").read_text()
    start = source.index("def worldgen_garden_stage0(")
    end = source.index("def _spawn_worker_call", start)
    section = source[start:end]
    assert "prompt: str = GARDEN_PANO_PROMPT" in section
    assert '"prompt": prompt' in section
    assert "prompt=prompt" in section
