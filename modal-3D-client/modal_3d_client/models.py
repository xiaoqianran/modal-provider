"""Model and profile lookup derived from the validated capability document."""

from __future__ import annotations

from .capabilities import CapabilityError, capabilities_document


def public_models() -> list[dict[str, object]]:
    return [dict(item) for item in capabilities_document()["models"]]  # type: ignore[index]


def _model(model_id: str) -> dict[str, object]:
    for model in public_models():
        if model.get("id") == model_id and model.get("status") == "enabled":
            return model
    raise CapabilityError(f"modal-3D model is unavailable: {model_id}")


def options_for(model_id: str, profile_id: str, seed: int) -> dict[str, object]:
    model = _model(model_id)
    for profile in model["profiles"]:  # type: ignore[index]
        if isinstance(profile, dict) and profile.get("id") == profile_id:
            options = dict(profile.get("options") or {})
            options["seed"] = seed
            return options
    raise CapabilityError(f"modal-3D profile is unavailable: {model_id}/{profile_id}")
