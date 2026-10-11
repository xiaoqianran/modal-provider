from .contracts import CONTRACT
from .models import list_models


def list_capabilities() -> tuple[dict[str, object], ...]:
    models = list_models()
    operations = sorted({op for model in models for op in model.operations})
    return tuple(
        {
            "id": op,
            "contract": CONTRACT,
            "models": [model.id for model in models if op in model.operations],
            "outputs": [{"role": "primary-text", "mediaType": "text/plain"}],
        }
        for op in operations
    )
