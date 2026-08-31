from pathlib import Path


def test_pipeline_uses_existing_stage_chain_and_runtime_artifact_roles():
    source = Path("modal_world/app.py").read_text()
    start = source.index("def worldgen_pipeline(")
    section = source[start:]
    for stage in range(1, 6):
        assert f"worldgen_case000_stage{stage}.remote" in section
    assert "worldgen_garden_stage0.remote" in section
    assert 'role="world-mesh"' in section
    assert 'role="world-semantics"' in section
    assert 'role="world-visual"' in section


def test_stage0_prompt_is_runtime_input_not_hardcoded_only():
    source = Path("modal_world/app.py").read_text()
    start = source.index("def worldgen_garden_stage0(")
    end = source.index("def _spawn_worker_call", start)
    section = source[start:end]
    assert "prompt: str = GARDEN_PANO_PROMPT" in section
    assert '"prompt": prompt' in section
    assert "prompt=prompt" in section
