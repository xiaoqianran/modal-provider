from pathlib import Path

from modal_world.stage1_patch import patch_stage1_worldnav


def test_stage1_dispatches_to_persistent_worldnav_worker():
    app = Path("modal_world/app.py").read_text()
    start = app.index('def worldgen_case000_stage1(job_id: str = "case000")')
    end = app.index("\n\n@app.function", start)
    proxy = app[start:end]
    assert 'modal.Cls.from_name("modal-world-stage2", "WorldNavRenderer")' in proxy
    assert ".generate_nav.remote(" in proxy
    assert "Qwen3VLEngine(" not in proxy
    assert "panorama_utils.write_text" not in proxy

    worker = Path("modal_world/stage2_app.py").read_text()
    assert "def generate_nav" in worker
    assert 'urlopen("http://127.0.0.1:8000/v1/models"' in worker
    assert 'stage="stage1"' in worker
    assert '"mesh_resolution": [480, 960]' in worker
    assert "model_load_s" in worker
    assert "runtime_cache.commit()" in worker


def test_stage1_patch_is_image_build_time():
    runtime = Path("modal_world/hyworld2_runtime.py").read_text()
    assert ".run_function(patch_stage1_worldnav" in runtime
    patch = Path("modal_world/stage1_patch.py").read_text()
    assert "get_panorama_cameras_v2" in patch
    assert "Open3D 0.18 native cleanup segfaults" in patch
    assert "NumPy Z-up -> Y-up rotation" in patch
    assert "mesh_h, mesh_w = 480, 960" in patch


def test_stage1_patch_matches_pinned_upstream(tmp_path: Path):
    src = Path("/tmp/hyworld2-src")
    required = (
        "hyworld2/worldgen/src/panorama_utils.py",
        "hyworld2/worldgen/src/navi_utils.py",
        "hyworld2/worldgen/traj_generate.py",
    )
    if not all((src / rel).is_file() for rel in required):
        return
    root = tmp_path / "source"
    for rel in required:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text((src / rel).read_text())
    patch_stage1_worldnav(root)
    panorama = (root / required[0]).read_text()
    navi = (root / required[1]).read_text()
    traj = (root / required[2]).read_text()
    assert "pole-safe up selection" in panorama
    assert "skipping Open3D native cleanup/boundary repair" in panorama
    assert "NumPy Z-up -> Y-up rotation" in navi
    assert "mesh_h, mesh_w = 480, 960" in traj


def test_stage1_uses_persistent_hf_cache_and_preloads_hidden_models():
    patch = Path("modal_world/stage1_patch.py").read_text()
    app = Path("modal_world/app.py").read_text()
    assert 'os.environ.get("HUGGINGFACE_HUB_CACHE"' in patch
    assert "def preload_worldnav_stage1_weights" in app
    assert '"naver-iv/zim-anything-vitl"' in app
    assert '"IDEA-Research/grounding-dino-tiny"' in app
    assert '"zim_vit_l_2092/**"' in app
    assert 'zim / "encoder.onnx"' in app
    assert 'zim / "decoder.onnx"' in app
