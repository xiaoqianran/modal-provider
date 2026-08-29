from pathlib import Path


def test_stage3_preloads_dinov2_and_forces_offline_camera_selector():
    app_source = Path("modal_world/app.py").read_text()
    patch_source = Path("modal_world/stage3_patch.py").read_text()
    runtime_source = Path("modal_world/hyworld2_runtime.py").read_text()
    assert '("facebook/dinov2-base", None)' in app_source
    assert 'snapshot_download("facebook/dinov2-base", local_files_only=True)' in app_source
    assert "model_path, use_fast=True, local_files_only=True" in patch_source
    assert "model_path, local_files_only=True" in patch_source
    assert ".run_function(patch_stage3_runtime" in runtime_source
