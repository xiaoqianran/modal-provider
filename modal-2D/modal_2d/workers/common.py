from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from ..artifacts import write_png
from ..contracts import normalize_batch_request, normalize_request
from ..runtime import encode_png


def generate_one(runtime, payload, *, model_id: str, infer: Callable, artifact_root: Path):
    request = normalize_request(payload)
    if request["model"] != model_id:
        raise ValueError("worker model does not match request model")
    image = infer(runtime, request)
    return write_png(artifact_root, encode_png(image, request))


def generate_many(
    runtime,
    payload,
    *,
    model_id: str,
    infer: Callable,
    artifact_root: Path,
    worker_load_ms: float | None,
    worker_reused: bool,
):
    batch = normalize_batch_request(payload)
    if batch["model"] != model_id:
        raise ValueError("worker model does not match request model")
    started = perf_counter()
    descriptors = []
    items = []
    for request in batch["requests"]:
        item_started = perf_counter()
        infer_started = perf_counter()
        image = infer(runtime, request)
        inference_ms = round((perf_counter() - infer_started) * 1000, 3)
        descriptor = write_png(artifact_root, encode_png(image, request))
        descriptors.append(descriptor)
        items.append(
            {
                "seed": request["seed"],
                "inference_ms": inference_ms,
                "total_ms": round((perf_counter() - item_started) * 1000, 3),
            }
        )
    return descriptors, {
        "worker_reused": worker_reused,
        "worker_load_ms": None if worker_reused else worker_load_ms,
        "batch_total_ms": round((perf_counter() - started) * 1000, 3),
        "items": items,
    }
