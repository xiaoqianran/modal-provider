from __future__ import annotations

import copy

import pytest

from modal_3d_client.models import IncompatibleCapability, _validate_document


def capability_document() -> dict[str, object]:
    return {
        "contract": "modal-3d.capabilities.v2",
        "provider": "modal-3d",
        "kind": "asset3d.generate",
        "operation": "modal-3d.asset.image_to_3d.v1",
        "outputs": [{"role": "primary-glb", "mediaType": "model/gltf-binary"}],
        "generation": {
            "app": "modal-3d-gateway",
            "submit_function": "submit",
            "job_transport": "modal.FunctionCall",
            "artifact_volume": "modal-3d-artifacts",
            "artifact_path_field": "path",
            "public_input_contract": {
                "role": "source_image",
                "mediaTypes": ["image/png", "image/jpeg", "image/webp"],
                "maxBytes": 20 * 1024 * 1024,
                "alpha": "optional",
                "conditioning": "provider",
                "pathPrefix": "source-inputs/",
            },
            "input_contract": {
                "role": "canonical_rgba",
                "mime": "image/png",
                "mode": "RGBA",
                "width": 1024,
                "height": 1024,
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
                "profiles": [{"id": "recommended", "options": {}}],
            }
        ],
    }


def test_public_input_contract_is_the_sidecar_boundary():
    document = _validate_document(capability_document())
    assert document["generation"]["public_input_contract"]["role"] == "source_image"


def test_legacy_canonical_contract_alone_is_not_enough():
    document = capability_document()
    del document["generation"]["public_input_contract"]
    with pytest.raises(IncompatibleCapability, match="public input contract"):
        _validate_document(document)


def test_public_input_contract_must_not_drift():
    document = copy.deepcopy(capability_document())
    document["generation"]["public_input_contract"]["conditioning"] = "caller"
    with pytest.raises(IncompatibleCapability, match="public input contract"):
        _validate_document(document)
