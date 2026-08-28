import pytest

from modal_2d.contracts import (
    ARTIFACT_MIME,
    CAPABILITY_KIND,
    DEFAULT_MODEL,
    MODELS,
    OPERATION,
    capabilities_document,
    model_spec,
    normalize_batch_request,
    normalize_request,
    validate_artifact_id,
    validate_normalized_request,
)


def test_registry_contains_only_sana_sprint_models():
    assert [model.id for model in MODELS] == ["sana-sprint-0.6b", "sana-sprint-1.6b"]
    assert all(model.hf_id.startswith("Efficient-Large-Model/Sana_Sprint_") for model in MODELS)
    assert all(model.steps == 2 for model in MODELS)
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
    assert doc["kind"] == CAPABILITY_KIND
    assert doc["operation"] == OPERATION
    assert doc["inputSchema"]["required"] == ["prompt"]
    assert doc["outputs"] == [{"role": "primary-image", "mediaType": ARTIFACT_MIME}]
    assert doc["execution"] == {"mode": "async", "cancellable": True}
    assert doc["generation"]["batch_submit_function"] == "submit_batch"
    assert doc["generation"]["batch_max_size"] == 8
    assert doc["artifact"] == {
        "role": "primary-image",
        "mime": ARTIFACT_MIME,
        "format": "png",
        "lossless": True,
    }
    assert [item["id"] for item in doc["models"]] == ["sana-sprint-0.6b", "sana-sprint-1.6b"]
    assert all(
        item["profiles"] == [{"id": "recommended", "steps": 2, "guidance": 4.5}]
        for item in doc["models"]
    )


def test_artifact_id_is_url_safe():
    assert validate_artifact_id("art_abc-123") == "art_abc-123"
    with pytest.raises(ValueError):
        validate_artifact_id("../secret")


def test_internal_normalized_request_is_separate_from_public_schema():
    normalized = normalize_request({"prompt": "mossy house"})
    assert validate_normalized_request(normalized) == normalized
    with pytest.raises(ValueError, match="fields are invalid"):
        validate_normalized_request({**normalized, "internal": True})
    with pytest.raises(ValueError, match="values are invalid"):
        validate_normalized_request({**normalized, "width": 512})


def test_batch_request_normalizes_one_prompt_with_multiple_unique_seeds():
    batch = normalize_batch_request({
        "prompt": "mossy house",
        "model": "sana-sprint-1.6b",
        "seeds": [42, 73, 104, 135],
    })
    assert batch["model"] == "sana-sprint-1.6b"
    assert [item["seed"] for item in batch["requests"]] == [42, 73, 104, 135]
    assert all(item["prompt"] == "mossy house" for item in batch["requests"])


def test_batch_request_rejects_duplicate_or_oversized_seeds():
    with pytest.raises(ValueError, match="unique"):
        normalize_batch_request({"prompt": "x", "seeds": [42, 42]})
    with pytest.raises(ValueError, match="between 1 and 8"):
        normalize_batch_request({"prompt": "x", "seeds": list(range(9))})
