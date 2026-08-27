import pytest

from modal_3d_client.constants import SOURCE_MEDIA_TYPES, SOURCE_PATH_PREFIX, SOURCE_ROLE
from modal_3d_client.contracts import ContractError, validate_artifact


def test_artifact_accepts_shared_and_legacy_identity():
    sha = "a" * 64
    artifact = validate_artifact(
        {
            "id": "art_1",
            "role": "primary-glb",
            "mediaType": "model/gltf-binary",
            "digest": f"sha256:{sha}",
            "mime": "model/gltf-binary",
            "sha256": sha,
            "bytes": 12,
            "path": "generated/a.glb",
            "producer": {
                "provider": "modal-3d",
                "operation": "modal-3d.asset.image_to_3d.v1",
                "model": "fastsam3d-plus-plus",
            },
        },
        model="fastsam3d-plus-plus",
    )
    assert artifact["digest"] == f"sha256:{sha}"


def test_artifact_rejects_identity_mismatch():
    sha = "a" * 64
    with pytest.raises(ContractError, match="digest"):
        validate_artifact(
            {
                "role": "primary-glb",
                "mime": "model/gltf-binary",
                "sha256": sha,
                "digest": "sha256:" + "b" * 64,
                "bytes": 12,
                "path": "generated/a.glb",
            },
            model="fastsam3d-plus-plus",
        )


def test_public_source_contract_constants_do_not_expose_provider_canonical_details():
    assert SOURCE_ROLE == "source_image"
    assert SOURCE_MEDIA_TYPES == ("image/png", "image/jpeg", "image/webp")
    assert SOURCE_PATH_PREFIX == "source-inputs/"
