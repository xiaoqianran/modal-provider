"""Single source of truth for image-to-3D models and direct worker routes."""

from __future__ import annotations

from types import MappingProxyType

from .specs import ModelSpec

_MODELS = {
    "hunyuan2.1-plus-plus": ModelSpec(
        "Archerkattri/hunyuan2.1-plus-plus", worker_app="modal-3d-hunyuan"
    ),
    "fastsam3d-plus-plus": ModelSpec(
        "Archerkattri/fastsam3d-plus-plus", worker_app="modal-3d-fastsam3d"
    ),
    "hermit-trellis2-plus-plus": ModelSpec(
        "Archerkattri/hermit-trellis2-plus-plus", worker_app="modal-3d-hermit-trellis2-plus-plus"
    ),
    "pixal3d": ModelSpec("TencentARC/Pixal3D", worker_app="modal-3d-pixal3d"),
}
MODELS = MappingProxyType(_MODELS)


def get_model(model_id: str) -> ModelSpec:
    return MODELS[model_id]


def list_models() -> tuple[str, ...]:
    return tuple(MODELS)


def generation_routes() -> dict[str, tuple[str, str, str]]:
    return {
        name: (model.worker_app, model.worker_class, model.remote_method)
        for name, model in MODELS.items()
    }
