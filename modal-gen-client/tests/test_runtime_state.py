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
