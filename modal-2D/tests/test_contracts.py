import pytest

from modal_2d.contracts import (
    ARTIFACT_MIME,
    DEFAULT_MODEL,
    MODELS,
    OPERATION,
    capabilities_document,
    model_spec,
    normalize_request,
    validate_artifact_id,
)


def test_registry_contains_only_sana_sprint_models():
    assert [model.id for model in MODELS] == ["sana-sprint-0.6b", "sana-sprint-1.6b"]
    assert all(model.hf_id.startswith("Efficient-Large-Model/Sana_Sprint_") for model in MODELS)
    assert model_spec(DEFAULT_MODEL).parameters == "1.6B"


def test_request_normalization_is_small_and_deterministic():
    assert normalize_request({"prompt": "  mossy house  "}) == {
        "prompt": "mossy house",
        "model": "sana-sprint-1.6b",
        "seed": 42,
        "steps": 2,
        "guidance": 4.5,
        "width": 1024,
        "height": 1024,
        "output": "png",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"prompt": "x", "model": "other"},
        {"prompt": "x", "steps": 0},
        {"prompt": "x", "steps": 5},
        {"prompt": "x", "guidance": float("nan")},
        {"prompt": "x", "seed": True},
        {"prompt": "x", "extra": 1},
    ],
)
def test_request_rejects_invalid_or_unknown_input(payload):
    with pytest.raises(ValueError):
        normalize_request(payload)


def test_capability_is_stable_and_lossless():
    doc = capabilities_document()
    assert doc["provider"] == "modal-2d"
    assert doc["operation"] == OPERATION
    assert doc["artifact"] == {
        "role": "primary-image",
        "mime": ARTIFACT_MIME,
        "format": "png",
        "lossless": True,
    }
    assert [item["id"] for item in doc["models"]] == ["sana-sprint-0.6b", "sana-sprint-1.6b"]


def test_artifact_id_is_url_safe():
    assert validate_artifact_id("art_abc-123") == "art_abc-123"
    with pytest.raises(ValueError):
        validate_artifact_id("../secret")
