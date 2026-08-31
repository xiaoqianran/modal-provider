from pathlib import Path


def test_panogen_image_is_dependency_isolated_from_worldnav():
    source = Path("modal_world/hyworld2_runtime.py").read_text()
    pano_start = source.index("hyworld2_panogen_image =")
    nav_start = source.index("hyworld2_worldgen_stage1_image =")
    pano = source[pano_start:nav_start]
    assert '"transformers[accelerate,tiktoken]==4.57.1"' in pano
    assert '"diffusers==0.36.0"' in pano
    assert '"peft==0.18.1"' in pano
    assert 'f"{HYWORLD2_SOURCE}/hyworld2/panogen:{HYWORLD2_SOURCE}"' in pano


def test_garden_stage0_generates_canonical_erp_and_persists_manifest():
    source = Path("modal_world/app.py").read_text()
    start = source.index("def worldgen_garden_stage0(")
    end = source.index("def _spawn_worker_call", start)
    section = source[start:end]
    assert "resolve_worldgen_job_root(job_id)" in section
    assert "target / source_name" in section
    assert 'target / "panorama.png"' in section
    assert 'stage="stage0"' in section
    assert '"Qwen/Qwen-Image-Edit-2509"' in section
    assert 'lora_subfolder="HY-Pano-2.0"' in section
    assert "num_inference_steps=40" in section
    assert "panorama.size != (1920, 960)" in section
    assert "worldgen_outputs.commit()" in section
