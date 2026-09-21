from __future__ import annotations

from copy import deepcopy

from .common import (
    CANONICAL_INPUT,
    INPUT_KINDS,
    OPERATION_IMAGE_TO_3D,
    OUTPUT_KINDS,
    WORKER_ADAPTER_REVISION,
)
from .router import ROUTES, WORKERS

CONTRACT = "modal-3d.capabilities.v3"
OPERATION_CONTRACT = "modal-3d.operations.v1"
PROFILE_RECOMMENDED = "recommended"
CANONICAL_INPUT_PATH_PREFIX = "client-inputs/"


def has_current_adapter_revision(capability: object) -> bool:
    """Check the historical adapter_revision field used as worker deployment revision."""
    if not isinstance(capability, dict):
        return False
    deployment = capability.get("deployment")
    return (
        isinstance(deployment, dict)
        and deployment.get("adapter_revision") == WORKER_ADAPTER_REVISION
    )


def _validate_io_descriptor(value: object, *, direction: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{direction} descriptor must be an object")
    name = value.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{direction} descriptor name must be a non-empty string")
    kind = value.get("kind")
    allowed = INPUT_KINDS if direction == "input" else OUTPUT_KINDS
    if kind not in allowed:
        raise ValueError(f"{direction} descriptor {name!r} has unsupported kind: {kind!r}")
    if direction == "input":
        required = value.get("required")
        if not isinstance(required, bool):
            raise TypeError(f"input descriptor {name!r} required must be boolean")
    contract = value.get("contract")
    if contract is not None and not isinstance(contract, dict):
        raise TypeError(f"{direction} descriptor {name!r} contract must be an object")
    artifact = value.get("artifact")
    if artifact is not None:
        if not isinstance(artifact, dict):
            raise TypeError(f"{direction} descriptor {name!r} artifact must be an object")
        mime = artifact.get("mime")
        extension = artifact.get("extension")
        if not isinstance(mime, str) or not mime:
            raise ValueError(f"{direction} descriptor {name!r} artifact.mime is required")
        if not isinstance(extension, str) or not extension.startswith("."):
            raise ValueError(
                f"{direction} descriptor {name!r} artifact.extension must start with '.'"
            )
    return deepcopy(value)


def validate_capability(capability: dict) -> dict:
    if not isinstance(capability, dict):
        raise TypeError("capability must be an object")
    required = {
        "id",
        "name",
        "description",
        "status",
        "worker_app",
        "operation",
        "inputs",
        "outputs",
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
    operation = capability.get("operation")
    if not isinstance(operation, str) or not operation:
        raise ValueError("operation must be a non-empty string")

    inputs = capability.get("inputs")
    outputs = capability.get("outputs")
    if not isinstance(inputs, list) or not inputs:
        raise TypeError("inputs must be a non-empty list")
    if not isinstance(outputs, list) or not outputs:
        raise TypeError("outputs must be a non-empty list")
    validated_inputs = [_validate_io_descriptor(value, direction="input") for value in inputs]
    validated_outputs = [_validate_io_descriptor(value, direction="output") for value in outputs]
    if len({item["name"] for item in validated_inputs}) != len(validated_inputs):
        raise ValueError("input descriptor names must be unique")
    if len({item["name"] for item in validated_outputs}) != len(validated_outputs):
        raise ValueError("output descriptor names must be unique")

    entrypoint = capability.get("entrypoint")
    if not isinstance(entrypoint, dict) or entrypoint.get("kind") != "class_method":
        raise TypeError("entrypoint must be a class_method object")
    for field in ("class_name", "method_name"):
        value = entrypoint.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"entrypoint.{field} must be a non-empty string")

    if operation == OPERATION_IMAGE_TO_3D:
        legacy_required = {"input", "output", "artifact", "generation_entrypoint"}
        legacy_missing = sorted(legacy_required - capability.keys())
        if legacy_missing:
            raise ValueError(
                f"image_to_3d capability missing legacy fields: {', '.join(legacy_missing)}"
            )
        if capability.get("output") not in {"geometry", "textured"}:
            raise ValueError("output must be geometry or textured")
        if capability["input"] != CANONICAL_INPUT:
            raise ValueError("worker input contract must be canonical 1024x1024 RGBA PNG")
        image_inputs = [item for item in validated_inputs if item["name"] == "image"]
        if len(image_inputs) != 1 or image_inputs[0].get("kind") != "image":
            raise ValueError("image_to_3d capability must declare one image input")
        if image_inputs[0].get("contract") != CANONICAL_INPUT:
            raise ValueError("image_to_3d image input must use the canonical RGBA contract")
        legacy_entrypoint = capability.get("generation_entrypoint")
        if (
            not isinstance(legacy_entrypoint, dict)
            or legacy_entrypoint.get("kind") != "class_method"
        ):
            raise TypeError("generation_entrypoint must be a class_method object")
        for field in ("class_name", "method_name"):
            value = legacy_entrypoint.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"generation_entrypoint.{field} must be a non-empty string")
        if legacy_entrypoint != entrypoint:
            raise ValueError("generation_entrypoint must match entrypoint")

    if not has_current_adapter_revision(capability):
        raise ValueError(f"worker deployment revision mismatch: expected {WORKER_ADAPTER_REVISION}")
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
    if reference_status is not None and reference_status not in {
        "verified",
        "stale",
        "legacy",
    }:
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
    return deepcopy(capability)


def assert_routable(capabilities: list[dict]) -> None:
    """Fail fast when a capability manifest disagrees with the local routing table."""
    for item in capabilities:
        capability_id = item.get("id")
        route_table = WORKERS if item.get("operation") == OPERATION_IMAGE_TO_3D else ROUTES
        entry = route_table.get(capability_id)
        if entry is None:
            raise ValueError(
                f"capability {capability_id!r} has no entry in the local routing table"
            )
        app_name, class_name, method_name = entry
        if item.get("worker_app") != app_name:
            raise ValueError(
                f"capability {capability_id!r} worker_app {item.get('worker_app')!r} "
                f"!= routing table {app_name!r}"
            )
        if item.get("operation") == OPERATION_IMAGE_TO_3D:
            entrypoint = item.get("generation_entrypoint") or {}
        else:
            entrypoint = item.get("entrypoint") or {}
        if (
            entrypoint.get("kind") != "class_method"
            or entrypoint.get("class_name") != class_name
            or entrypoint.get("method_name") != method_name
        ):
            raise ValueError(
                f"capability {capability_id!r} entrypoint does not match the routing table"
            )


def _registered_capabilities(capabilities: list[dict] | None = None) -> list[dict]:
    if capabilities is None:
        return []
    return sorted(
        (
            validate_capability(deepcopy(item))
            for item in capabilities
            if has_current_adapter_revision(item)
        ),
        key=lambda item: (item.get("priority", 1000), item["id"]),
    )


def capabilities_document(models: list[dict] | None = None) -> dict:
    """Build one backward-compatible document for generation and generic 3D operations."""
    assert_routable(models or [])
    registered = _registered_capabilities(models)
    generation_models = [
        deepcopy(item) for item in registered if item.get("operation") == OPERATION_IMAGE_TO_3D
    ]
    return {
        "contract": CONTRACT,
        "generation": {
            "job_transport": "modal.FunctionCall",
            "entrypoint": "direct_class_method",
            "input_path_prefix": CANONICAL_INPUT_PATH_PREFIX,
            "input_contract": deepcopy(CANONICAL_INPUT),
        },
        "operations": {
            "contract": OPERATION_CONTRACT,
            "job_transport": "modal.FunctionCall",
            "entrypoint": "direct_class_method",
            "input_kinds": sorted(INPUT_KINDS),
            "output_kinds": sorted(OUTPUT_KINDS),
        },
        "models": generation_models,
        "capabilities": registered,
    }


def model_capability(model: str, models: list[dict]) -> dict:
    for item in models:
        if item.get("id") == model:
            if not has_current_adapter_revision(item):
                raise ValueError(
                    f"model {model} worker deployment is stale; redeploy required "
                    f"({WORKER_ADAPTER_REVISION})"
                )
            return validate_capability(deepcopy(item))
    raise ValueError(f"unknown model: {model}")


def worker_app(model: str, models: list[dict]) -> str:
    return str(model_capability(model, models)["worker_app"])


def profile_options(model: str, profile_id: str, models: list[dict]) -> dict:
    capability = model_capability(model, models)
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


def validate_options(model: str, options: dict | None, models: list[dict]) -> dict:
    return validate_options_for_capability(model_capability(model, models), options)
