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
    generation = doc["generation"]
    assert generation["app"] == "modal-2d"
    assert generation["worker_class"] == "SanaSprintWorker"
    assert generation["generate_method"] == "generate"
    assert generation["batch_generate_method"] == "generate_batch"
    assert generation["artifact_function"] == "read_artifact"
    assert generation["job_transport"] == "modal-function-call"
    assert "submit_function" not in generation
    assert "batch_submit_function" not in generation
    assert generation["batch_max_size"] == 8
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


def test_public_schema_cannot_carry_internal_generation_fields():
    """Worker 直接接受 public payload，内部字段只能由服务端 normalize 产生。"""
    for field in ("steps", "width", "height", "output"):
        with pytest.raises(ValueError, match="unknown generation fields"):
            normalize_request({"prompt": "mossy house", field: 512})

    normalized = normalize_request({"prompt": "mossy house"})
    assert normalized["steps"] == 2 and normalized["width"] == 1024
    public = {key: normalized[key] for key in ("prompt", "model", "seed", "guidance")}
    assert normalize_request(public) == normalized


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
