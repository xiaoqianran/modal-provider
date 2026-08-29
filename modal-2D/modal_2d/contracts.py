from __future__ import annotations

import math
import re
from typing import Any

from .constants import ARTIFACT_FORMAT, MAX_BATCH_SIZE, MAX_PROMPT_CHARS, MAX_SEED
from .models import DEFAULT_MODEL, model_spec

_SAFE_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


def normalize_request(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("generation request must be an object")
    allowed = {"prompt", "model", "seed", "guidance"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        names = ", ".join(unknown)
        raise ValueError(f"unknown generation fields: {names}")

    raw_prompt = value.get("prompt")
    if not isinstance(raw_prompt, str) or not raw_prompt.strip():
        raise ValueError("prompt is required")
    prompt = raw_prompt.strip()
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt exceeds {MAX_PROMPT_CHARS} characters")

    raw_model = value.get("model", DEFAULT_MODEL)
    if not isinstance(raw_model, str):
        raise ValueError("model must be a string")
    model = model_spec(raw_model)
    seed = _integer(value.get("seed", 42), "seed", 0, MAX_SEED)
    guidance = model.guidance
    if "guidance" in value:
        guidance = _number(value["guidance"], "guidance", 0.0, 20.0)
        if not model.guidance_editable and guidance != model.guidance:
            raise ValueError(f"{model.id} guidance is fixed at {model.guidance}")
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
        names = ", ".join(unknown)
        raise ValueError(f"unknown batch generation fields: {names}")
    seeds = value.get("seeds")
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= MAX_BATCH_SIZE:
        raise ValueError(f"seeds must contain between 1 and {MAX_BATCH_SIZE} integers")
    validated = [_integer(seed, "seed", 0, MAX_SEED) for seed in seeds]
    if len(set(validated)) != len(validated):
        raise ValueError("seeds must be unique")
    base = {key: value[key] for key in ("prompt", "model", "guidance") if key in value}
    requests = [normalize_request({**base, "seed": seed}) for seed in validated]
    return {"model": str(requests[0]["model"]), "requests": requests}


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
