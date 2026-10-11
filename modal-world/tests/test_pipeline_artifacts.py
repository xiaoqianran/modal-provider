import pytest

from modal_world.pipelines.artifacts import collect_world_artifacts
from modal_world.worldgen_job import runtime_result_dir, stage5_artifacts


def test_artifact_collection_includes_optional_navigation(tmp_path):
    target = tmp_path / "worldgen" / "jobs" / "job-1"
    runtime = runtime_result_dir(target, 8000)
    runtime.mkdir(parents=True)
    for name in ("environment.ply", "semantics.json", "world.json"):
        (runtime / name).write_bytes(b"valid")
    visual = stage5_artifacts(target, 8000).spz
    visual.parent.mkdir(parents=True)
    visual.write_bytes(b"visual")
    without_nav = collect_world_artifacts(target, "job-1", 8000, volume_root=tmp_path / "worldgen")
    assert [item["role"] for item in without_nav] == ["world-mesh", "world-semantics", "world-visual", "world-manifest"]
    (runtime / "navigation.ply").write_bytes(b"navigation")
    with_nav = collect_world_artifacts(target, "job-1", 8000, volume_root=tmp_path / "worldgen")
    assert with_nav[-1]["role"] == "world-navigation"
    assert all(len(item["sha256"]) == 64 for item in with_nav)


def test_missing_artifact_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="World artifact missing"):
        collect_world_artifacts(tmp_path / "worldgen" / "jobs" / "job-2", "job-2", 8000)
