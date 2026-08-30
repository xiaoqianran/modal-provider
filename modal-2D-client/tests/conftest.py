import hashlib

import pytest


@pytest.fixture
def capability_doc():
    return {
        "contract": "modal-2d.generation.v2",
        "provider": "modal-2d",
        "kind": "image.generate",
        "operation": "modal-2d.image.text_to_image.v1",
        "generation": {
            "entrypoint": "direct_class_method",
            "batch_max_size": 8,
            "artifact_volume": "modal-gen-artifacts",
            "artifact_path_field": "remote_path",
            "job_transport": "modal.FunctionCall",
        },
        "outputs": [{"role": "primary-image", "mediaType": "image/png"}],
        "input": {"prompt": {"type": "string"}, "size": {"width": 1024, "height": 1024}},
        "artifact": {
            "role": "primary-image",
            "mime": "image/png",
            "format": "png",
            "lossless": True,
        },
        "models": [
            {
                "id": "sana-sprint-1.6b",
                "name": "SANA-Sprint 1.6B",
                "hf_id": "Efficient-Large-Model/Sana_Sprint_1.6B_1024px_diffusers",
                "parameters": "1.6B",
                "steps": 2,
                "guidance": 4.5,
                "width": 1024,
                "height": 1024,
                "profiles": [{"id": "recommended", "steps": 2, "guidance": 4.5}],
                "generation_entrypoint": {
                    "app": "modal-2d-sana-sprint",
                    "class_name": "Model",
                    "generate_method": "generate",
                    "batch_generate_method": "generate_batch",
                },
            }
        ],
    }


@pytest.fixture
def png_artifact():
    data = b"\x89PNG\r\n\x1a\nbody"
    sha256 = hashlib.sha256(data).hexdigest()
    return data, {
        "id": "art_abc",
        "role": "primary-image",
        "mediaType": "image/png",
        "digest": f"sha256:{sha256}",
        "producer": {"provider": "modal-2d", "operation": "modal-2d.image.text_to_image.v1"},
        "mime": "image/png",
        "format": "png",
        "bytes": len(data),
        "sha256": sha256,
        "width": 1024,
        "height": 1024,
        "remote_path": f"sources/sha256/{sha256[:2]}/{sha256}",
    }
