from modal_3d.config import MODELS as LEGACY_MODELS
from modal_3d.config import ModelSpec as LegacyModelSpec
from modal_3d.models import MODELS, ModelSpec, generation_routes, get_model, list_models
from modal_3d.router import WORKERS, resolve


def test_registry_legacy_compatibility():
    assert MODELS is LEGACY_MODELS
    assert ModelSpec is LegacyModelSpec
    assert set(list_models()) == set(WORKERS)
    for model_id in list_models():
        assert get_model(model_id) is MODELS[model_id]
        assert generation_routes()[model_id] == resolve(model_id)
        assert MODELS[model_id].worker_app == WORKERS[model_id][0]
