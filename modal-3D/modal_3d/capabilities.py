from __future__ import annotations

from copy import deepcopy
from typing import Protocol

import modal

from .common import CANONICAL_INPUT, REGISTRY_NAME, WORKER_ADAPTER_REVISION

CONTRACT = "modal-3d.capabilities.v2"
PROFILE_RECOMMENDED = "recommended"
PUBLIC_IMAGE_INPUT = {
    "role": "source_image",
    "mediaTypes": ["image/png", "image/jpeg", "image/webp"],
    "maxBytes": 20 * 1024 * 1024,
    "alpha": "optional",
    "conditioning": "provider",
    "pathPrefix": "source-inputs/",
}


class Registry(Protocol):
    def get(self, key, default=None): ...

    def items(self): ...


def model_registry() -> modal.Dict:
    return modal.Dict.from_name(REGISTRY_NAME, create_if_missing=True)


def has_current_adapter_revision(capability: object) -> bool:
    if not isinstance(capability, dict):
        return False
    deployment = capability.get("deployment")
    return (
        isinstance(deployment, dict)
        and deployment.get("adapter_revision") == WORKER_ADAPTER_REVISION
    )


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
        "deployment",
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
    if capability["input"] != CANONICAL_INPUT:
        raise ValueError("worker input contract must be canonical 1024x1024 RGBA PNG")
    if not has_current_adapter_revision(capability):
        raise ValueError(
            f"worker adapter revision mismatch: expected {WORKER_ADAPTER_REVISION}"
        )
    profiles, options = capability["profiles"], capability["options"]
    if not isinstance(profiles, list) or not profiles or not isinstance(options, dict):
        raise TypeError("profiles must be non-empty and options must be an object")
    for profile in profiles:
        if not isinstance(profile, dict) or not isinstance(profile.get("options"), dict):
            raise TypeError("each profile must contain an options object")
        unknown = sorted(set(profile["options"]) - set(options))
        if unknown:
            raise ValueError(f"profile references unknown options: {', '.join(unknown)}")
        quality = profile.get("quality")
        if quality is not None:
            if not isinstance(quality, dict):
                raise TypeError("profile.quality must be an object")
            tier = quality.get("tier")
            if tier not in {"full_quality", "accelerated"}:
                raise ValueError("profile.quality.tier must be full_quality or accelerated")
            basis = quality.get("basis")
            if not isinstance(basis, str) or not basis:
                raise ValueError("profile.quality.basis must be a non-empty string")
            verification = quality.get("verification")
            if not isinstance(verification, dict) or verification.get("status") not in {
                "verified",
                "stale",
                "unverified",
            }:
                raise ValueError(
                    "profile.quality.verification.status must be verified, stale, or unverified"
                )
            benchmark = verification.get("benchmark")
            if verification.get("status") in {"verified", "stale"} and (
                not isinstance(benchmark, str) or not benchmark
            ):
                raise ValueError("verified/stale profile quality requires a benchmark path")
    reference = capability.get("reference", {})
    warm_seconds = reference.get("warm_seconds")
    if (
        not isinstance(warm_seconds, (int, float))
        or isinstance(warm_seconds, bool)
        or warm_seconds <= 0
    ):
        raise TypeError("reference.warm_seconds must be a positive number")
    reference_status = reference.get("status")
    if reference_status is not None and reference_status not in {"verified", "stale", "legacy"}:
        raise ValueError("reference.status must be verified, stale, or legacy")
    benchmark = reference.get("benchmark")
    if benchmark is not None and (not isinstance(benchmark, str) or not benchmark):
        raise ValueError("reference.benchmark must be a non-empty string when present")

    cold_start_seconds = reference.get("cold_start_seconds")
    if cold_start_seconds is not None and (
        not isinstance(cold_start_seconds, (int, float))
        or isinstance(cold_start_seconds, bool)
        or cold_start_seconds <= 0
    ):
        raise TypeError("reference.cold_start_seconds must be a positive number when present")

    entrypoint = capability.get("generation_entrypoint")
    if entrypoint is not None:
        if not isinstance(entrypoint, dict) or entrypoint.get("kind") != "class_method":
            raise TypeError("generation_entrypoint must be a class_method object")
        for field in ("class_name", "method_name"):
            value = entrypoint.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"generation_entrypoint.{field} must be a non-empty string")
    return deepcopy(capability)


def _registered_models(registry: Registry | None = None) -> list[dict]:
    source = registry if registry is not None else model_registry()
    # Registry entries survive redeploys. Never advertise a Worker whose adapter
    # revision predates the current serialized runtime contract. This turns a
    # stale deployment into an explicit unavailable model instead of routing new
    # paid work into a container-start retry loop.
    models = [
        validate_capability(value)
        for _, value in source.items()
        if has_current_adapter_revision(value)
    ]
    return sorted(models, key=lambda item: (item.get("priority", 1000), item["id"]))


def capabilities_document(registry: Registry | None = None) -> dict:
    models = _registered_models(registry)
    for model in models:
        # Internal Modal routing metadata is intentionally not part of the
        # client-facing capabilities contract.
        model.pop("generation_entrypoint", None)
    return {
        "contract": CONTRACT,
        "generation": {
            "app": "modal-3d-gateway",
            "submit_function": "submit",
            "job_transport": "modal.FunctionCall",
            "public_input_contract": deepcopy(PUBLIC_IMAGE_INPUT),
            # Legacy/internal worker contract kept during the strangler migration.
            "input_contract": deepcopy(CANONICAL_INPUT),
        },
        "models": models,
    }


def model_capability(model: str, registry: Registry | None = None) -> dict:
    source = registry if registry is not None else model_registry()
    capability = source.get(model)
    if capability is None:
        raise ValueError(f"unknown model: {model}")
    if not has_current_adapter_revision(capability):
        raise ValueError(
            f"model {model} worker deployment is stale; redeploy required "
            f"({WORKER_ADAPTER_REVISION})"
        )
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


def validate_options_for_capability(capability: dict, options: dict | None) -> dict:
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


def validate_options(model: str, options: dict | None, registry: Registry | None = None) -> dict:
    return validate_options_for_capability(model_capability(model, registry), options)
