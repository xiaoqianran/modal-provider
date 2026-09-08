from pathlib import Path

import pytest

from modal_world.worldgen_job import (
    build_stage_manifest,
    fingerprint_files,
    manifest_matches,
    resolve_worldgen_job_root,
    runtime_result_dir,
    stage5_artifacts,
    stage5_result_dir,
    stage_profile_name,
    write_stage_manifest,
)


def test_job_paths_preserve_case000_and_isolate_new_jobs():
    assert resolve_worldgen_job_root("case000") == Path("/worldgen/case000")
    assert resolve_worldgen_job_root("job-abc_123") == Path("/worldgen/jobs/job-abc_123")
    for bad in ("", "../escape", "/absolute", "a/b", " space"):
        with pytest.raises(ValueError):
            resolve_worldgen_job_root(bad)


def test_stage_manifest_invalidates_changed_inputs(tmp_path: Path):
    source = tmp_path / "input.bin"
    source.write_bytes(b"first")
    fingerprint = fingerprint_files([source], root=tmp_path)
    manifest = build_stage_manifest(
        job_id="job1",
        stage="stage2",
        hyworld_revision="rev",
        input_fingerprint=fingerprint,
        config={"quality": 1},
    )
    write_stage_manifest(tmp_path, "stage2", manifest)
    assert manifest_matches(tmp_path, "stage2", manifest)

    source.write_bytes(b"second")
    changed = build_stage_manifest(
        job_id="job1",
        stage="stage2",
        hyworld_revision="rev",
        input_fingerprint=fingerprint_files([source], root=tmp_path),
        config={"quality": 1},
    )
    assert not manifest_matches(tmp_path, "stage2", changed)


def test_stage2_and_stage4_accept_job_id_and_use_manifest():
    app = Path("modal_world/app.py").read_text()
    stage2 = Path("modal_world/stage2_app.py").read_text()
    stage45_core = Path("modal_world/stage45_core.py").read_text()
    assert 'def worldgen_case000_stage2(' not in app
    assert "worldnav_worker.render" in app
    assert 'def worldgen_case000_stage4(job_id: str = "case000", force: bool = False)' in app
    assert 'manifest_matches(target, "stage2"' in stage2
    assert 'write_stage_manifest(target, "stage2"' in stage2
    assert 'manifest_matches(target, "stage4"' in stage45_core
    assert 'write_stage_manifest(target, "stage4"' in stage45_core


def test_stage5_artifacts_follow_trainer_zero_based_output_step(tmp_path: Path):
    outputs = stage5_artifacts(tmp_path, 100)
    assert outputs.ply == tmp_path / "gs_result_steps_100/ply/point_cloud_99.ply"
    assert outputs.spz == tmp_path / "gs_result_steps_100/ply/point_cloud_99.spz"
    assert outputs.mesh == tmp_path / "gs_result_steps_100/ply/fuse_post.ply"

    final = stage5_artifacts(tmp_path, 8000)
    assert final.ply == tmp_path / "gs_result/ply/point_cloud_7999.ply"
    assert final.spz == tmp_path / "gs_result/ply/point_cloud_7999.spz"
    assert stage5_result_dir(tmp_path, 8000) == tmp_path / "gs_result"
    assert stage5_result_dir(tmp_path, 2000) == tmp_path / "gs_result_steps_2000"
    assert runtime_result_dir(tmp_path, 8000) == tmp_path / "runtime"
    assert runtime_result_dir(tmp_path, 2000) == tmp_path / "runtime_steps_2000"
    assert stage_profile_name("stage5", 8000) == "stage5"
    assert stage_profile_name("stage5", 2000) == "stage5-steps-2000"
    with pytest.raises(ValueError, match="steps must be > 0"):
        stage5_artifacts(tmp_path, 0)
