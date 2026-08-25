import hashlib

import pytest


@pytest.fixture
def capability_doc():
    return {
        "contract": "modal-2d.generation.v1",
        "provider": "modal-2d",
        "operation": "modal-2d.image.text_to_image.v1",
        "generation": {
            "app": "modal-2d",
            "submit_function": "submit",
            "artifact_function": "read_artifact",
            "job_transport": "modal-function-call",
        },
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
            }
        ],
    }


@pytest.fixture
def png_artifact():
    data = b"\x89PNG\r\n\x1a\nbody"
    return data, {
        "id": "art_abc",
        "role": "primary-image",
        "mime": "image/png",
        "format": "png",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": 1024,
        "height": 1024,
    }
