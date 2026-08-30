from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeAppState:
    """Normalized runtime facts for one deployment target."""

    app: str
    deployment_status: str
    required: bool
    models: tuple[str, ...]
    weights_status: str
    error: object | None
    runnable: bool

    @classmethod
    def from_mapping(cls, item: dict[str, object]) -> RuntimeAppState:
        deployment_status = str(item.get("status") or "unknown")
        weights = item.get("weights")
        weights_status = (
            str(weights.get("status") or "unknown") if isinstance(weights, dict) else "not_required"
        )
        explicit_runnable = item.get("runnable")
        runnable = (
            explicit_runnable
            if isinstance(explicit_runnable, bool)
            else deployment_status == "current" and weights_status in {"ready", "not_required"}
        )
        return cls(
            app=str(item.get("app") or "unknown"),
            deployment_status=deployment_status,
            required=item.get("required") is True,
            models=tuple(model for model in item.get("models", []) if isinstance(model, str)),
            weights_status=weights_status,
            error=item.get("error") or item.get("weightError"),
            runnable=runnable,
        )

    @property
    def deployed(self) -> bool:
        return self.deployment_status not in {"missing", "error", "failed", "unknown"}

    @property
    def revision_current(self) -> bool:
        return self.deployment_status == "current"

    @property
    def weights_ready(self) -> bool:
        return self.weights_status in {"ready", "not_required"}

    @property
    def model_state(self) -> str:
        if self.runnable:
            return "ready"
        if self.deployment_status == "stale":
            return "outdated"
        if self.deployment_status == "missing":
            return "not_deployed"
        if self.deployment_status == "error":
            return "error"
        return "weights_missing" if not self.weights_ready else "blocked"

    def model_readiness(self, model: str) -> dict[str, object]:
        return {
            "model": model,
            "app": self.app,
            "state": self.model_state,
            "runnable": self.runnable,
            "deploymentStatus": self.deployment_status,
            "weightsStatus": self.weights_status,
            "error": self.error,
        }

    def blocker(self) -> dict[str, object]:
        return {"app": self.app, "status": self.deployment_status, "error": self.error}


def project_runtime_readiness(
    descriptor: dict[str, object], readiness: dict[str, object]
) -> dict[str, object]:
    """Project runtime facts onto a provider descriptor without changing its public shape."""

    runtime = _first_runtime(readiness)
    if runtime is None or not isinstance(runtime.get("apps"), list):
        return descriptor

    states = [
        RuntimeAppState.from_mapping(item) for item in runtime["apps"] if isinstance(item, dict)
    ]
    required_blockers = [
        state.blocker() for state in states if state.required and not state.runnable
    ]
    ready_models = {model for state in states if state.runnable for model in state.models}
    model_readiness = [state.model_readiness(model) for state in states for model in state.models]

    projected = deepcopy(descriptor)
    projected["runtimeReadiness"] = runtime
    capabilities = projected.get("capabilities")
    if not isinstance(capabilities, list):
        return projected

    any_available = False
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        model_schema = _model_schema(capability)
        if model_schema is None:
            continue
        declared_models = model_schema.get("enum")
        if not isinstance(declared_models, list):
            continue

        capability["declaredModels"] = list(declared_models)
        capability["modelReadiness"] = [
            row for row in model_readiness if row["model"] in declared_models
        ]
        runnable_models = [model for model in declared_models if model in ready_models]
        model_schema["enum"] = runnable_models
        capability["readyModels"] = list(runnable_models)

        if not runnable_models:
            capability["status"] = "disabled"
            continue
        any_available = True
        if required_blockers:
            capability["status"] = "degraded"
            capability["runtimeBlockers"] = required_blockers

    if not any_available:
        projected["status"] = "disabled"
        projected["health"] = "unavailable"
    elif required_blockers:
        projected["status"] = "degraded"
        projected["health"] = "degraded"
        projected["runtimeBlockers"] = required_blockers
    return projected


def _first_runtime(readiness: dict[str, object]) -> dict[str, object] | None:
    providers = readiness.get("providers")
    if not isinstance(providers, list) or not providers:
        return None
    runtime = providers[0]
    return runtime if isinstance(runtime, dict) else None


def _model_schema(capability: dict[str, object]) -> dict[str, object] | None:
    input_desc = capability.get("input")
    if not isinstance(input_desc, dict):
        return None
    schema = input_desc.get("schema")
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    model = properties.get("model")
    return model if isinstance(model, dict) else None
