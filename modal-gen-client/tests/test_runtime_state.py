from __future__ import annotations

from modal_gen.runtime_state import RuntimeAppState, project_runtime_readiness


def test_runtime_state_separates_deployment_revision_and_weights() -> None:
    stale = RuntimeAppState.from_mapping(
        {
            "app": "worker",
            "status": "stale",
            "models": ["model-a"],
            "weights": {"status": "ready"},
        }
    )
    assert stale.deployed is True
    assert stale.revision_current is False
    assert stale.weights_ready is True
    assert stale.runnable is False
    assert stale.model_state == "outdated"

    missing_weights = RuntimeAppState.from_mapping(
        {
            "app": "worker",
            "status": "current",
            "models": ["model-a"],
            "weights": {"status": "missing"},
        }
    )
    assert missing_weights.deployed is True
    assert missing_weights.revision_current is True
    assert missing_weights.weights_ready is False
    assert missing_weights.runnable is False
    assert missing_weights.model_state == "weights_missing"


def test_runtime_projection_preserves_invalid_readiness_as_noop() -> None:
    descriptor = {"id": "modal-x", "status": "available", "capabilities": []}
    assert project_runtime_readiness(descriptor, {"providers": []}) is descriptor


def test_advanced_worker_status_is_independent_of_image_generation():
    descriptor = {
        "id": "modal-3d",
        "status": "available",
        "health": "healthy",
        "capabilities": [
            {
                "operation": "image_to_3d",
                "status": "available",
                "input": {"schema": {"properties": {"model": {"enum": ["base"]}}}},
            },
            {
                "operation": "segment_parts",
                "runtimeTarget": "modal-3d-p3sam",
                "status": "available",
                "input": {"schema": {"properties": {}}},
            },
            {
                "operation": "retopology",
                "runtimeTarget": "modal-3d-mesh",
                "status": "available",
                "input": {"schema": {"properties": {}}},
            },
        ],
    }
    runtime = {
        "providers": [
            {
                "apps": [
                    {"app": "model", "status": "missing", "models": ["base"]},
                    {"app": "modal-3d-p3sam", "status": "current", "models": ["segment_parts"]},
                    {"app": "modal-3d-mesh", "status": "stale", "models": ["retopology"]},
                ]
            }
        ]
    }
    result = project_runtime_readiness(descriptor, runtime)
    caps = {x["operation"]: x for x in result["capabilities"]}
    assert caps["image_to_3d"]["status"] == "disabled"
    assert caps["segment_parts"]["status"] == "available"
    assert caps["retopology"]["status"] == "disabled"
    assert caps["retopology"]["runtimeTargetReadiness"]["state"] == "outdated"
    assert result["status"] == "degraded"


def test_missing_worker_never_becomes_runnable():
    descriptor = {
        "id": "modal-3d",
        "status": "available",
        "capabilities": [
            {"operation": "pose", "status": "available", "runtimeTarget": "modal-3d-pose"}
        ],
    }
    result = project_runtime_readiness(descriptor, {"providers": [{"apps": []}]})
    assert result["status"] == "disabled"
    assert result["capabilities"][0]["status"] == "disabled"
    assert result["capabilities"][0]["runtimeBlockers"][0]["app"] == "modal-3d-pose"
