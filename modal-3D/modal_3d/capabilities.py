from __future__ import annotations

from copy import deepcopy
from typing import Protocol

import modal

from .common import REGISTRY_NAME

CONTRACT = "modal-3d.capabilities.v1"
PROFILE_RECOMMENDED = "recommended"


class Registry(Protocol):
    def get(self, key, default=None): ...

    def items(self): ...


def model_registry() -> modal.Dict:
    return modal.Dict.from_name(REGISTRY_NAME, create_if_missing=True)


def validate_capability(capability: dict) -> dict:
    if not isinstance(capability, dict):
        raise TypeError("capability must be an object")
    required = {
        "id",
        "name",
        "description",
        "status",
        "worker_app",
        "output",
        "artifact",
        "input",
        "profiles",
        "options",
        "reference",
    }
    missing = sorted(required - capability.keys())
    if missing:
        raise ValueError(f"capability missing fields: {', '.join(missing)}")
    if not isinstance(capability["id"], str) or not capability["id"]:
        raise ValueError("capability id must be a non-empty string")
    if capability["status"] != "enabled":
        raise ValueError("only enabled workers may register")
    if not isinstance(capability["worker_app"], str) or not capability["worker_app"]:
        raise ValueError("worker_app must be a non-empty string")
    if capability.get("output") not in {"geometry", "textured"}:
        raise ValueError("output must be geometry or textured")
    profiles, options = capability["profiles"], capability["options"]
    if not isinstance(profiles, list) or not profiles or not isinstance(options, dict):
        raise TypeError("profiles must be non-empty and options must be an object")
    for profile in profiles:
        if not isinstance(profile, dict) or not isinstance(profile.get("options"), dict):
            raise TypeError("each profile must contain an options object")
        unknown = sorted(set(profile["options"]) - set(options))
        if unknown:
            raise ValueError(f"profile references unknown options: {', '.join(unknown)}")
    reference = capability.get("reference", {})
    warm_seconds = reference.get("warm_seconds")
    if not isinstance(warm_seconds, (int, float)) or isinstance(warm_seconds, bool):
        raise TypeError("reference.warm_seconds must be a number")
    return deepcopy(capability)


def _registered_models(registry: Registry | None = None) -> list[dict]:
    source = registry if registry is not None else model_registry()
    models = [validate_capability(value) for _, value in source.items()]
    return sorted(models, key=lambda item: (item.get("priority", 1000), item["id"]))


def capabilities_document(registry: Registry | None = None) -> dict:
    return {
        "contract": CONTRACT,
        "generation": {
            "app": "modal-3d-gateway",
            "submit_function": "submit",
            "pipeline_function": "generate_from_raw",
            "job_transport": "modal.FunctionCall",
            "http": {"submit": "/tasks", "pipeline": "/pipelines", "status": "/tasks/{task_id}"},
        },
        "models": _registered_models(registry),
        "sam": {
            "cloud": {
                "app": "modal-3d-sam31",
                "provider": "cloud",
                "operations": ["segment", "refine", "materialize"],
                "sam3_code_revision": "8f0b7f4d4e7eda2ed606ebde6702c93359ad01da",
                "sam31_revision": "daa63191845a41281374e725f4c9e51c7a824460",
                "canonical": {
                    "mime": "image/png",
                    "mode": "RGBA",
                    "square": True,
                    "default_size": 1024,
                },
            }
        },
    }


def model_capability(model: str, registry: Registry | None = None) -> dict:
    source = registry if registry is not None else model_registry()
    capability = source.get(model)
    if capability is None:
        raise ValueError(f"unknown model: {model}")
    return validate_capability(capability)


def worker_app(model: str, registry: Registry | None = None) -> str:
    return str(model_capability(model, registry)["worker_app"])


def profile_options(model: str, profile_id: str, registry: Registry | None = None) -> dict:
    capability = model_capability(model, registry)
    profile = next((item for item in capability["profiles"] if item["id"] == profile_id), None)
    if profile is None:
        raise ValueError(f"model {capability['id']} does not support profile: {profile_id}")
    return dict(profile["options"])


def _validate_value(name: str, value, schema: dict) -> None:
    if value is None:
        if schema.get("nullable"):
            return
        raise ValueError(f"option {name} must not be null")

    expected = schema["type"]
    if expected == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif expected == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif expected == "string":
        valid = isinstance(value, str)
    elif expected == "boolean":
        valid = isinstance(value, bool)
    else:
        raise RuntimeError(f"unsupported option schema type: {expected}")
    if not valid:
        raise ValueError(f"option {name} must be {expected}")

    allowed = schema.get("enum")
    if allowed is not None and value not in allowed:
        raise ValueError(f"option {name} must be one of: {allowed}")

    minimum = schema.get("minimum")
    if minimum is not None and value < minimum:
        raise ValueError(f"option {name} must be >= {minimum}")
    maximum = schema.get("maximum")
    if maximum is not None and value > maximum:
        raise ValueError(f"option {name} must be <= {maximum}")


def validate_options(model: str, options: dict | None, registry: Registry | None = None) -> dict:
    capability = model_capability(model, registry)
    if options is None:
        return {}
    if not isinstance(options, dict):
        raise TypeError("options must be an object")

    schemas = capability["options"]
    unknown = sorted(set(options) - set(schemas))
    if unknown:
        raise ValueError(f"unknown options for {capability['id']}: {', '.join(unknown)}")

    validated = dict(options)
    for name, value in validated.items():
        _validate_value(name, value, schemas[name])
    return validated
