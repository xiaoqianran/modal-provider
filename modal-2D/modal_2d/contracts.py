from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

APP_NAME = "modal-2d"
PROVIDER = "modal-2d"
CONTRACT = "modal-2d.generation.v1"
CAPABILITY_KIND = "image.generate"
OPERATION = "modal-2d.image.text_to_image.v1"
ARTIFACT_ROLE = "primary-image"
ARTIFACT_MIME = "image/png"
ARTIFACT_FORMAT = "png"
ARTIFACT_VOLUME = "modal-2d-artifacts"
IMAGE_SIZE = 1024
MAX_PROMPT_CHARS = 4000
MAX_SEED = 2**32 - 1
MAX_BATCH_SIZE = 8
_SAFE_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    name: str
    hf_id: str
    parameters: str
    steps: int = 2
    guidance: float = 4.5
    gpu: str = "L40S"
    width: int = IMAGE_SIZE
    height: int = IMAGE_SIZE


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="sana-sprint-0.6b",
        name="SANA-Sprint 0.6B",
        hf_id="Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers",
        parameters="0.6B",
    ),
    ModelSpec(
        id="sana-sprint-1.6b",
        name="SANA-Sprint 1.6B",
        hf_id="Efficient-Large-Model/Sana_Sprint_1.6B_1024px_diffusers",
        parameters="1.6B",
    ),
)
DEFAULT_MODEL = "sana-sprint-1.6b"
_MODEL_MAP = {model.id: model for model in MODELS}


def model_spec(model_id: str) -> ModelSpec:
    try:
        return _MODEL_MAP[model_id]
    except KeyError as exc:
        raise ValueError(f"unsupported model: {model_id}") from exc


def normalize_request(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("generation request must be an object")
    allowed = {"prompt", "model", "seed", "guidance"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown generation fields: {', '.join(unknown)}")

    prompt = str(value.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt exceeds {MAX_PROMPT_CHARS} characters")

    model = model_spec(str(value.get("model") or DEFAULT_MODEL))
    seed = _integer(value.get("seed", 42), "seed", 0, MAX_SEED)
    guidance = _number(value.get("guidance", model.guidance), "guidance", 0.0, 20.0)
    return {
        "prompt": prompt,
        "model": model.id,
        "seed": seed,
        "steps": model.steps,
        "guidance": guidance,
        "width": model.width,
        "height": model.height,
        "output": ARTIFACT_FORMAT,
    }



def normalize_batch_request(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("batch generation request must be an object")
    allowed = {"prompt", "model", "seeds", "guidance"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown batch generation fields: {', '.join(unknown)}")
    seeds = value.get("seeds")
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= MAX_BATCH_SIZE:
        raise ValueError(f"seeds must contain between 1 and {MAX_BATCH_SIZE} integers")
    if len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be unique")
    base = {key: value[key] for key in ("prompt", "model", "guidance") if key in value}
    requests = [normalize_request({**base, "seed": seed}) for seed in seeds]
    model = str(requests[0]["model"])
    return {"model": model, "requests": requests}

def validate_normalized_request(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("normalized generation request must be an object")
    expected_keys = {
        "prompt",
        "model",
        "seed",
        "steps",
        "guidance",
        "width",
        "height",
        "output",
    }
    if set(value) != expected_keys:
        raise ValueError("normalized generation request fields are invalid")
    public = {key: value[key] for key in ("prompt", "model", "seed", "guidance")}
    normalized = normalize_request(public)
    if normalized != value:
        raise ValueError("normalized generation request values are invalid")
    return normalized


def capabilities_document() -> dict[str, object]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string", "minLength": 1, "maxLength": MAX_PROMPT_CHARS},
            "model": {"type": "string", "enum": [model.id for model in MODELS]},
            "seed": {"type": "integer", "minimum": 0, "maximum": MAX_SEED},
            "guidance": {"type": "number", "minimum": 0.0, "maximum": 20.0},
        },
    }
    return {
        "contract": CONTRACT,
        "provider": PROVIDER,
        "kind": CAPABILITY_KIND,
        "operation": OPERATION,
        "inputSchema": schema,
        "outputs": [{"role": ARTIFACT_ROLE, "mediaType": ARTIFACT_MIME}],
        "execution": {"mode": "async", "cancellable": True},
        "generation": {
            "app": APP_NAME,
            "submit_function": "submit",
            "prefetch_function": "prefetch",
            "batch_submit_function": "submit_batch",
            "batch_max_size": MAX_BATCH_SIZE,
            "artifact_function": "read_artifact",
            "artifact_volume": ARTIFACT_VOLUME,
            "artifact_path_field": "remote_path",
            "job_transport": "modal-function-call",
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
        "models": [
            {
                **asdict(model),
                "profiles": [
                    {"id": "recommended", "steps": model.steps, "guidance": model.guidance},
                ],
            }
            for model in MODELS
        ],
    }


def validate_artifact_id(value: str) -> str:
    artifact_id = str(value or "").strip()
    if not _SAFE_ARTIFACT_ID.fullmatch(artifact_id):
        raise ValueError("artifact id must be URL-safe")
    return artifact_id


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return result
