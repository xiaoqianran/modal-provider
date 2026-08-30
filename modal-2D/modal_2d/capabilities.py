from __future__ import annotations

from .constants import (
    ARTIFACT_FORMAT,
    ARTIFACT_MIME,
    ARTIFACT_ROLE,
    ARTIFACT_VOLUME,
    CAPABILITY_KIND,
    CONTRACT,
    IMAGE_SIZE,
    JOB_TRANSPORT,
    MAX_BATCH_SIZE,
    MAX_PROMPT_CHARS,
    MAX_SEED,
    OPERATION,
    PROVIDER,
)
from .models import MODELS


def capabilities_document() -> dict[str, object]:
    return {
        "contract": CONTRACT,
        "provider": PROVIDER,
        "kind": CAPABILITY_KIND,
        "operation": OPERATION,
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["prompt"],
            "properties": {
                "prompt": {"type": "string", "minLength": 1, "maxLength": MAX_PROMPT_CHARS},
                "model": {"type": "string", "enum": [model.id for model in MODELS]},
                "seed": {"type": "integer", "minimum": 0, "maximum": MAX_SEED},
                "guidance": {"type": "number", "minimum": 0.0, "maximum": 20.0},
            },
        },
        "outputs": [{"role": ARTIFACT_ROLE, "mediaType": ARTIFACT_MIME}],
        "execution": {"mode": "async", "cancellable": True},
        "generation": {
            "entrypoint": "direct_class_method",
            "artifact_volume": ARTIFACT_VOLUME,
            "artifact_path_field": "remote_path",
            "job_transport": JOB_TRANSPORT,
            "batch_max_size": MAX_BATCH_SIZE,
        },
        "input": {
            "prompt": {"type": "string", "minLength": 1, "maxLength": MAX_PROMPT_CHARS},
            "size": {"width": IMAGE_SIZE, "height": IMAGE_SIZE},
        },
        "artifact": {
            "role": ARTIFACT_ROLE,
            "mime": ARTIFACT_MIME,
            "format": ARTIFACT_FORMAT,
            "lossless": True,
        },
        "models": [model.public() for model in MODELS],
    }
