from modal_world.deployment import deployment_manifest
from modal_world.models import MODELS, get_model, list_models
from modal_world.providers import register_builtin_backends
from modal_world.registry import get_backend, list_backends


def test_model_registry_deployment_backend_consistency():
    assert tuple(model.id for model in list_models()) == ("hyworld2",)
    model = get_model("hyworld2")
    assert MODELS[model.id] is model
    register_builtin_backends()
    assert model.backend in list_backends()
    backend = get_backend(model.backend)
    assert model.backend == backend.name
    assert {operation.value for operation in backend.capability.operations} == set(model.operations)
    targets = deployment_manifest()["targets"]
    assert {target["app"] for target in targets if model.id in target["models"]} == set(model.deployment_apps)
    assert len(model.deployment_apps) == len(set(model.deployment_apps))
