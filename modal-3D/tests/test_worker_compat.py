from modal_3d import mesh_worker
from modal_3d.workers import mesh
from modal_3d.workers.catalog import validate_worker_modules


def test_mesh_worker_entrypoint_aliases_original_app_and_class():
    assert mesh_worker.app is mesh.app
    assert mesh_worker.Model is mesh.Model
    assert mesh_worker.artifacts is mesh.artifacts
    assert not validate_worker_modules()
