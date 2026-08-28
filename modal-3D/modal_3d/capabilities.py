from __future__ import annotations

from copy import deepcopy

from .common import CANONICAL_INPUT, WORKER_ADAPTER_REVISION
from .router import WORKERS

# v3 drops the gateway: submissions are spawned directly against each worker's
# GPU `Model.generate_job` class method using the local static routing table.
CONTRACT = "modal-3d.capabilities.v3"
PROFILE_RECOMMENDED = "recommended"
# The client uploads a finished canonical input; Modal never preprocesses.
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
            f"worker deployment revision mismatch: expected {WORKER_ADAPTER_REVISION}"
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


def assert_routable(models: list[dict]) -> None:
    """Fail fast when a worker manifest disagrees with the local routing table.

    `router.WORKERS` is what the client actually spawns against, so a mismatch
    between it and a worker's declared `generation_entrypoint` must be caught at
    build/test time rather than on a paid GPU call.
    """
    for item in models:
        model_id = item.get("id")
        entry = WORKERS.get(model_id)
        if entry is None:
            raise ValueError(f"model {model_id!r} has no entry in the local routing table")
        app_name, class_name, method_name = entry
        if item.get("worker_app") != app_name:
            raise ValueError(
                f"model {model_id!r} worker_app {item.get('worker_app')!r} != routing table {app_name!r}"
            )
        entrypoint = item.get("generation_entrypoint") or {}
        if (
            entrypoint.get("kind") != "class_method"
            or entrypoint.get("class_name") != class_name
            or entrypoint.get("method_name") != method_name
        ):
            raise ValueError(
                f"model {model_id!r} generation_entrypoint does not match the routing table"
            )


def _registered_models(models: list[dict] | None = None) -> list[dict]:
    if models is None:
        return []
    # Worker manifests are compiled into the client. Never advertise one whose
    # adapter revision predates the current serialized runtime contract: that
    # turns a stale manifest into an explicit unavailable model instead of
    # routing paid work into a container that cannot satisfy the contract.
    return sorted(
        (
            validate_capability(deepcopy(item))
            for item in models
            if has_current_adapter_revision(item)
        ),
        key=lambda item: (item.get("priority", 1000), item["id"]),
    )


def capabilities_document(models: list[dict] | None = None) -> dict:
    """Build the client-facing capability document from local worker manifests.

    `models` are the `CAPABILITY` dicts declared by each worker module. There is
    no dynamic registry: routing metadata is published per model because the
    client resolves every worker itself through `router.WORKERS`.
    """
    assert_routable(models or [])
    return {
        "contract": CONTRACT,
        "generation": {
            "job_transport": "modal.FunctionCall",
            "entrypoint": "direct_class_method",
            "input_path_prefix": CANONICAL_INPUT_PATH_PREFIX,
            "input_contract": deepcopy(CANONICAL_INPUT),
        },
        "models": _registered_models(models),
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
