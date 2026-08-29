import pytest

from modal_2d.capabilities import capabilities_document
from modal_2d.constants import ARTIFACT_MIME, CAPABILITY_KIND, OPERATION
from modal_2d.contracts import normalize_batch_request, normalize_request, validate_artifact_id
from modal_2d.models import DEFAULT_MODEL, MODELS, model_spec


def test_registry_contains_all_production_models():
    assert [model.id for model in MODELS] == [
        "sana-sprint-0.6b",
        "sana-sprint-1.6b",
        "qwen-image-2512",
        "z-image-turbo",
        "hidream-o1-image",
    ]
    assert model_spec(DEFAULT_MODEL).parameters == "1.6B"
    assert all(len(model.revision) == 40 for model in MODELS)
    assert all(model.worker_app.startswith("modal-2d-") for model in MODELS)


def test_model_recipes_are_explicit_and_stable():
    assert model_spec("sana-sprint-1.6b").steps == 2
    assert model_spec("qwen-image-2512").steps == 50
    assert model_spec("qwen-image-2512").guidance == 4.0
    assert model_spec("z-image-turbo").steps == 9
    assert model_spec("z-image-turbo").guidance == 0.0
    assert model_spec("z-image-turbo").guidance_editable is False
    assert model_spec("hidream-o1-image").steps == 50
    assert model_spec("hidream-o1-image").guidance == 5.0


def test_request_normalization_uses_model_recipe():
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
    qwen = normalize_request({"prompt": "mossy house", "model": "qwen-image-2512"})
    assert (qwen["steps"], qwen["guidance"]) == (50, 4.0)
    zimage = normalize_request({"prompt": "mossy house", "model": "z-image-turbo"})
    assert (zimage["steps"], zimage["guidance"]) == (9, 0.0)


def test_z_image_turbo_guidance_is_fixed():
    with pytest.raises(ValueError, match="guidance is fixed"):
        normalize_request({"prompt": "x", "model": "z-image-turbo", "guidance": 1.0})


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"prompt": "x", "model": "other"},
        {"prompt": "x", "steps": 5},
        {"prompt": "x", "guidance": float("nan")},
        {"prompt": "x", "seed": True},
        {"prompt": "x", "extra": 1},
        {"prompt": 123},
        {"prompt": "x", "model": 123},
        {"prompt": "x", "model": ""},
    ],
)
def test_request_rejects_invalid_or_unknown_input(payload):
    with pytest.raises(ValueError):
        normalize_request(payload)


def test_capability_routes_every_model_to_its_worker():
    doc = capabilities_document()
    assert doc["provider"] == "modal-2d"
    assert doc["kind"] == CAPABILITY_KIND
    assert doc["operation"] == OPERATION
    assert doc["outputs"] == [{"role": "primary-image", "mediaType": ARTIFACT_MIME}]
    generation = doc["generation"]
    assert generation["control_app"] == "modal-2d"
    assert generation["job_transport"] == "modal.FunctionCall"
    assert generation["batch_max_size"] == 8
    routes = {item["id"]: item["generation_entrypoint"] for item in doc["models"]}
    assert routes["sana-sprint-1.6b"]["app"] == "modal-2d-sana-sprint"
    assert routes["qwen-image-2512"]["app"] == "modal-2d-qwen-image-2512"
    assert routes["z-image-turbo"]["app"] == "modal-2d-z-image-turbo"
    assert routes["hidream-o1-image"]["app"] == "modal-2d-hidream-o1"
    assert all(route["class_name"] == "Model" for route in routes.values())


def test_artifact_id_is_url_safe():
    assert validate_artifact_id("art_abc-123") == "art_abc-123"
    with pytest.raises(ValueError):
        validate_artifact_id("../secret")


def test_public_schema_cannot_carry_internal_generation_fields():
    for field in ("steps", "width", "height", "output"):
        with pytest.raises(ValueError, match="unknown generation fields"):
            normalize_request({"prompt": "mossy house", field: 512})


def test_batch_request_normalizes_one_prompt_with_multiple_unique_seeds():
    batch = normalize_batch_request(
        {
            "prompt": "mossy house",
            "model": "qwen-image-2512",
            "seeds": [42, 73, 104, 135],
        }
    )
    assert batch["model"] == "qwen-image-2512"
    assert [item["seed"] for item in batch["requests"]] == [42, 73, 104, 135]
    assert all(item["steps"] == 50 for item in batch["requests"])


def test_batch_request_rejects_duplicate_or_oversized_seeds():
    with pytest.raises(ValueError, match="unique"):
        normalize_batch_request({"prompt": "x", "seeds": [42, 42]})
    with pytest.raises(ValueError, match="between 1 and 8"):
        normalize_batch_request({"prompt": "x", "seeds": list(range(9))})
