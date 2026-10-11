import re
from types import MappingProxyType

from .specs import ModelSpec


def build_registry(models: tuple[ModelSpec, ...]):
    result = {}
    for model in models:
        if not re.fullmatch(r"[a-z0-9]+(?:[-.][a-z0-9]+)*", model.id):
            raise ValueError(f"invalid model ID: {model.id}")
        if model.id in result:
            raise ValueError(f"duplicate model ID: {model.id}")
        if not model.operations or len(set(model.operations)) != len(model.operations):
            raise ValueError("operations must be nonempty and unique")
        result[model.id] = model
    return MappingProxyType(result)


MODELS = (
    ModelSpec(
        id="echo-text",
        name="CPU Echo",
        runtime="python",
        worker_app="modal-example-echo",
        gpu=None,
        operations=("modal-example.text.echo.v1",),
        worker_module="modal_example.workers.echo",
        worker_class="EchoWorker",
        business_method="echo",
        remote_method="run_job",
    ),
)
MODEL_REGISTRY = build_registry(MODELS)


def get_model(model_id: str) -> ModelSpec:
    return MODEL_REGISTRY[model_id]


def list_models() -> tuple[ModelSpec, ...]:
    return MODELS
