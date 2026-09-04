from pathlib import Path

from modal_world.backends.hyworld2 import HYWorld2Backend


def test_discovers_only_canonical_runtime_roles_for_generated_world_files(tmp_path: Path):
    paths = [
        tmp_path / "render_results/global_mesh.ply",
        tmp_path / "objects.json",
        tmp_path / "camera_trajectory/target_camera.json",
        tmp_path / "checkpoints/final.spz",
        tmp_path / "navmesh/metadata.json",
        tmp_path / "runtime/environment.ply",
        tmp_path / "runtime/navigation.ply",
        tmp_path / "runtime/world.json",
        tmp_path / "runtime/semantics.json",
        tmp_path / "gs_result/ply/point_cloud_7999.spz",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    artifacts = HYWorld2Backend._discover_artifacts(tmp_path)
    by_path = {item.path.relative_to(tmp_path).as_posix(): item for item in artifacts}

    assert by_path["runtime/environment.ply"].role == "world-mesh"
    assert by_path["runtime/navigation.ply"].role == "world-navigation"
    assert by_path["runtime/world.json"].role == "world-manifest"
    assert by_path["runtime/semantics.json"].role == "world-semantics"
    assert by_path["gs_result/ply/point_cloud_7999.spz"].role == "world-visual"

    assert by_path["render_results/global_mesh.ply"].role is None
    assert by_path["objects.json"].role is None
    assert by_path["checkpoints/final.spz"].role is None
    assert by_path["camera_trajectory/target_camera.json"].role is None
    assert by_path["navmesh/metadata.json"].role is None
