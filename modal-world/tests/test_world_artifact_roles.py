from pathlib import Path

from modal_world.backends.hyworld2 import HYWorld2Backend


def test_discovers_stable_runtime_roles_for_generated_world_files(tmp_path: Path):
    mesh = tmp_path / "render_results/global_mesh.ply"
    semantics = tmp_path / "objects.json"
    camera = tmp_path / "camera_trajectory/target_camera.json"
    visual = tmp_path / "checkpoints/final.spz"
    other = tmp_path / "navmesh/metadata.json"
    for path in (mesh, semantics, camera, visual, other):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    artifacts = HYWorld2Backend._discover_artifacts(tmp_path)
    by_path = {item.path.relative_to(tmp_path).as_posix(): item for item in artifacts}

    assert by_path["render_results/global_mesh.ply"].role == "world-mesh"
    assert by_path["objects.json"].role == "world-semantics"
    assert by_path["camera_trajectory/target_camera.json"].role is None
    assert by_path["checkpoints/final.spz"].role == "world-visual"
    assert by_path["navmesh/metadata.json"].role is None
