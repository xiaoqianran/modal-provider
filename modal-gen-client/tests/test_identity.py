from modal_gen.identity import idempotency_key, request_hash


def test_identity_matches_agentscape_reference_vector():
    request = {
        "provider": "modal-3d",
        "operation": "modal-3d.asset.image_to_3d.v1",
        "inputs": {
            "image": {
                "artifactId": "artifact_01",
                "hash": "sha256:" + "a" * 64,
                "mime": "image/png",
            },
            "concept": "mossy shrine",
        },
        "profile": "recommended",
        "options": {"model": "fastsam3d", "seed": 42},
        "outputRoles": ["primary-glb"],
        "parent": None,
        "retention": None,
        "metadata": None,
    }
    assert request_hash(request) == (
        "sha256:4b2daa5d5bf3b9b0dd161802779261443d98201d569840cdebf75df5a5262aee"
    )
    assert idempotency_key(request) == "idem_4b2daa5d5bf3b9b0dd161802779261443d98201d"


def test_identity_matches_agentscape_number_unicode_vector():
    request = {
        "provider": "modal-3d",
        "operation": "modal-3d.asset.image_to_3d.v1",
        "inputs": {"10": "ten", "2": "two", "concept": "数值测试"},
        "profile": "recommended",
        "options": {"scale": 1.0, "tiny": 1e-7, "huge": 1.2e20, "scientific": 1e21},
        "outputRoles": ["primary-glb"],
        "parent": None,
        "retention": None,
        "metadata": None,
    }
    assert request_hash(request) == (
        "sha256:fffa303387f676ad25b78c76a9e50fd7116c1007c21b0fb6f9d79b956075444a"
    )
    assert idempotency_key(request) == "idem_fffa303387f676ad25b78c76a9e50fd7116c1007"
