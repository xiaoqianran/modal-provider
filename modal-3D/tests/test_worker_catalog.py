from modal_3d.deployment import deployment_manifest
from modal_3d.models import generation_routes
from modal_3d.workers.catalog import list_workers, validate_worker_modules


def test_worker_catalog_matches_deployment_and_routes():
    entries = list_workers()
    assert len(entries) == len(deployment_manifest()["targets"])
    assert not validate_worker_modules()
    assert len({worker.app for worker in entries}) == len(entries)
    routes = generation_routes()
    for model, (app, _cls, _method) in routes.items():
        assert any(worker.app == app and model in worker.models for worker in entries)
