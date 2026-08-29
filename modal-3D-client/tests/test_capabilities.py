from __future__ import annotations

import copy

import pytest

from modal_3d_client.capabilities import IncompatibleCapability, _validate_document


def capability_document() -> dict[str, object]:
    return {
        "contract": "modal-3d.capabilities.v3",
        "provider": "modal-3d",
        "kind": "asset3d.generate",
        "operation": "modal-3d.asset.image_to_3d.v1",
        "outputs": [{"role": "primary-glb", "mediaType": "model/gltf-binary"}],
        "generation": {
            "job_transport": "modal.FunctionCall",
            "entrypoint": "direct_class_method",
            "input_path_prefix": "client-inputs/",
            "artifact_volume": "modal-3d-artifacts",
            "artifact_path_field": "path",
            "input_contract": {
                "role": "canonical_rgba",
                "mime": "image/png",
                "mode": "RGBA",
                "width": 1024,
                "height": 1024,
                "bit_depth": 8,
                "layout": "letterbox",
                "alpha": "channel_required",
            },
        },
        "models": [
            {
                "id": "fastsam3d-plus-plus",
                "status": "enabled",
                "artifact": {
                    "role": "primary-glb",
                    "mediaType": "model/gltf-binary",
                    "mime": "model/gltf-binary",
                },
                "generation_entrypoint": {
                    "kind": "class_method",
                    "class_name": "Model",
                    "method_name": "generate_job",
                },
                "profiles": [{"id": "recommended", "options": {}}],
            }
        ],
    }


def test_no_gateway_identity_is_advertised():
    document = _validate_document(capability_document())
    generation = document["generation"]
    assert "app" not in generation
    assert "submit_function" not in generation
    assert generation["entrypoint"] == "direct_class_method"
    assert generation["input_path_prefix"] == "client-inputs/"


def test_canonical_input_contract_is_required():
    document = capability_document()
    del document["generation"]["input_contract"]
    with pytest.raises(IncompatibleCapability, match="canonical input contract"):
        _validate_document(document)


def test_canonical_input_contract_must_not_drift():
    document = copy.deepcopy(capability_document())
    document["generation"]["input_contract"]["width"] = 512
    with pytest.raises(IncompatibleCapability, match="canonical input contract"):
        _validate_document(document)


def test_indirect_entrypoint_is_rejected():
    document = copy.deepcopy(capability_document())
    document["generation"]["entrypoint"] = "gateway_submit"
    with pytest.raises(IncompatibleCapability, match="entrypoint"):
        _validate_document(document)


def test_worker_without_direct_generate_job_is_rejected():
    document = copy.deepcopy(capability_document())
    del document["models"][0]["generation_entrypoint"]
    with pytest.raises(IncompatibleCapability, match="generate_job"):
        _validate_document(document)


def test_installed_capability_document_is_valid_and_routable():
    from modal_3d_client import capabilities
    from modal_3d_client.workers import WORKERS

    document = capabilities.capabilities_document()
    assert document["contract"] == "modal-3d.capabilities.v3"
    assert {model["id"] for model in document["models"]} == set(WORKERS)
