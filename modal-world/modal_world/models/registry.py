"""Canonical static World model catalog. Backend factories stay in registry.py."""
from __future__ import annotations

from types import MappingProxyType

from .specs import ModelSpec

_MODELS = {
    "hyworld2": ModelSpec(
        id="hyworld2",
        backend="hyworld2",
        operations=("reconstruct", "generate"),
        deployment_apps=(
            "modal-world", "modal-world-stage2", "modal-world-stage3",
            "modal-world-stage45", "modal-world-runtime-compile",
        ),
    ),
}
MODELS = MappingProxyType(_MODELS)


def get_model(model_id: str) -> ModelSpec:
    return MODELS[model_id]


def list_models() -> tuple[ModelSpec, ...]:
    return tuple(MODELS.values())
