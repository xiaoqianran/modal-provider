from __future__ import annotations

import math
import re
from typing import Any

from .constants import (
    ARTIFACT_MIME,
    ARTIFACT_ROLE,
    ARTIFACT_VOLUME,
    CONTRACT,
    DEFAULT_MODEL,
    JOB_TRANSPORT,
    MAX_BATCH_SIZE,
    MAX_PROMPT_CHARS,
    MAX_SEED,
    OPERATION,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


class ContractError(RuntimeError):
    pass


def validate_capabilities(value: Any) -> dict[str, object]:
    doc = _mapping(value, "capabilities")
    expected = {"contract": CONTRACT, "provider": "modal-2d", "operation": OPERATION}
    if any(doc.get(key) != item for key, item in expected.items()):
        raise ContractError("incompatible modal-2D capability identity")
    if doc.get("kind") not in (None, "image.generate"):
        raise ContractError("incompatible modal-2D capability kind")
    outputs = doc.get("outputs")
    if outputs is not None and outputs != [{"role": ARTIFACT_ROLE, "mediaType": ARTIFACT_MIME}]:
        raise ContractError("incompatible modal-2D capability outputs")

    generation = _mapping(doc.get("generation"), "generation")
    required_generation = {
        "entrypoint": "direct_class_method",
        "job_transport": JOB_TRANSPORT,
    }
    if any(generation.get(key) != item for key, item in required_generation.items()):
        raise ContractError("incompatible modal-2D generation endpoint")
    if generation.get("artifact_volume") not in (None, ARTIFACT_VOLUME):
        raise ContractError("incompatible modal-2D artifact volume")
    if generation.get("batch_max_size") not in (None, MAX_BATCH_SIZE):
        raise ContractError("incompatible modal-2D batch size")
    if generation.get("artifact_path_field") not in (None, "remote_path"):
        raise ContractError("incompatible modal-2D artifact path field")

    artifact = _mapping(doc.get("artifact"), "artifact")
    if (
        artifact.get("role") != ARTIFACT_ROLE
        or artifact.get("mime") != ARTIFACT_MIME
        or artifact.get("lossless") is not True
    ):
        raise ContractError("modal-2D artifact contract must be lossless primary-image PNG")

    models = doc.get("models")
    if not isinstance(models, list) or not models:
        raise ContractError("capabilities.models must be a non-empty array")
    seen: set[str] = set()
    for index, model in enumerate(models):
        item = _mapping(model, f"models[{index}]")
        model_id = _text(item.get("id"), f"models[{index}].id")
        if model_id in seen:
            raise ContractError(f"duplicate model id: {model_id}")
        seen.add(model_id)
        _text(item.get("name"), f"models[{index}].name")
        _text(item.get("hf_id"), f"models[{index}].hf_id")
        if item.get("width") != 1024 or item.get("height") != 1024:
            raise ContractError(f"model {model_id} must produce 1024x1024")
        steps = item.get("steps")
        if not isinstance(steps, int) or isinstance(steps, bool) or steps <= 0:
            raise ContractError(f"model {model_id} steps must be a positive integer")
        profiles = item.get("profiles")
        if not isinstance(profiles, list) or len(profiles) != 1:
            raise ContractError(f"model {model_id} requires one recommended profile")
        profile = _mapping(profiles[0], f"models[{index}].profiles[0]")
        if profile.get("id") != "recommended" or profile.get("steps") != steps:
            raise ContractError(f"model {model_id} profile is incompatible")
        route = _mapping(
            item.get("generation_entrypoint"),
            f"models[{index}].generation_entrypoint",
        )
        for field in ("app", "class_name", "generate_method", "batch_generate_method"):
            _text(route.get(field), f"models[{index}].generation_entrypoint.{field}")
    if DEFAULT_MODEL not in seen:
        raise ContractError(f"default model is unavailable: {DEFAULT_MODEL}")
    return doc


def normalize_request(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ContractError("generation request must be an object")
    allowed = {"prompt", "model", "seed", "guidance"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ContractError(f"unknown generation fields: {', '.join(unknown)}")
    raw_prompt = value.get("prompt")
    if not isinstance(raw_prompt, str):
        raise ContractError("prompt must be a string")
    prompt = raw_prompt.strip()
    if not prompt or len(prompt) > MAX_PROMPT_CHARS:
        raise ContractError("prompt is empty or too long")
    raw_model = value.get("model", DEFAULT_MODEL)
    if not isinstance(raw_model, str):
        raise ContractError("model must be a string")
    model = raw_model.strip()
    if not model:
        raise ContractError("model is required")
    seed = _integer(value.get("seed", 42), "seed", 0, MAX_SEED)
    result: dict[str, object] = {"prompt": prompt, "model": model, "seed": seed}
    if value.get("guidance") is not None:
        guidance = value["guidance"]
        if (
            not isinstance(guidance, (int, float))
            or isinstance(guidance, bool)
            or not math.isfinite(float(guidance))
            or not 0 <= float(guidance) <= 20
        ):
            raise ContractError("guidance must be a finite number in [0, 20]")
        result["guidance"] = float(guidance)
    return result


def normalize_batch_request(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ContractError("batch generation request must be an object")
    allowed = {"prompt", "model", "seeds", "guidance"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ContractError(f"unknown batch generation fields: {', '.join(unknown)}")
    seeds = value.get("seeds")
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= MAX_BATCH_SIZE:
        raise ContractError(f"seeds must contain between 1 and {MAX_BATCH_SIZE} integers")
    normalized_seeds = [_integer(seed, "seed", 0, MAX_SEED) for seed in seeds]
    if len(set(normalized_seeds)) != len(normalized_seeds):
        raise ContractError("seeds must be unique")
    single = normalize_request(
        {key: value[key] for key in ("prompt", "model", "guidance") if key in value}
    )
    single.pop("seed")
    return {**single, "seeds": normalized_seeds}


def validate_artifact(value: Any) -> dict[str, object]:
    artifact = _mapping(value, "artifact")
    artifact_id = _text(artifact.get("id"), "artifact.id")
    if not _SAFE_ID.fullmatch(artifact_id):
        raise ContractError("artifact.id must be URL-safe")
    if (
        artifact.get("role") != ARTIFACT_ROLE
        or artifact.get("mime") != ARTIFACT_MIME
        or artifact.get("format") != "png"
    ):
        raise ContractError("artifact role/mime/format is incompatible")
    size = artifact.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0 or size > 2**53 - 1:
        raise ContractError("artifact.bytes is invalid")
    digest = artifact.get("sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ContractError("artifact.sha256 is invalid")
    if artifact.get("mediaType") not in (None, ARTIFACT_MIME):
        raise ContractError("artifact.mediaType is incompatible")
    if artifact.get("digest") not in (None, f"sha256:{digest}"):
        raise ContractError("artifact.digest does not match artifact.sha256")
    producer = artifact.get("producer")
    if producer is not None and producer != {"provider": "modal-2d", "operation": OPERATION}:
        raise ContractError("artifact.producer is incompatible")
    remote_path = artifact.get("remote_path")
    if remote_path is not None and remote_path != f"generated/{artifact_id}.png":
        raise ContractError("artifact.remote_path is incompatible")
    if artifact.get("width") != 1024 or artifact.get("height") != 1024:
        raise ContractError("artifact dimensions are incompatible")
    return artifact


def _mapping(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value.strip()


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ContractError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value
