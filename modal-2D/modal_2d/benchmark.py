from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from .capabilities import MAX_BATCH_SIZE, capabilities_document

DEFAULT_BATCHES = (1, 2, 4, 8)
DEFAULT_PROMPT = "a red fox sitting in a snowy forest, cinematic photo, no text"


def parse_batches(value: str, maximum: int = MAX_BATCH_SIZE) -> tuple[int, ...]:
    try:
        batches = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("batches must be comma-separated integers") from exc
    if not batches or any(batch < 1 or batch > maximum for batch in batches):
        raise ValueError(f"batch sizes must be in [1, {maximum}]")
    if len(set(batches)) != len(batches):
        raise ValueError("batch sizes must be unique")
    return batches


def canonical_gpu_name(value: str) -> str:
    normalized = value.strip().upper().replace("_", "-")
    if "RTX" in normalized and "PRO" in normalized and "6000" in normalized:
        return "RTX-PRO-6000"
    for name in ("L40S", "H100", "A100", "B200", "L4", "T4"):
        if name in normalized:
            return name
    return value.strip()


def parse_gpu_rates(values: list[str]) -> dict[str, float]:
    rates: dict[str, float] = {}
    for value in values:
        gpu, separator, raw_rate = value.partition("=")
        if not separator or not gpu.strip():
            raise ValueError("GPU rates must use GPU=USD_PER_HOUR")
        try:
            rate = float(raw_rate)
        except ValueError as exc:
            raise ValueError(f"invalid GPU rate: {value}") from exc
        if rate < 0:
            raise ValueError("GPU rates must be non-negative")
        rates[canonical_gpu_name(gpu)] = rate
    return rates


def artifact_stats(artifacts: list[dict[str, object]]) -> dict[str, object]:
    sizes = [int(item["bytes"]) for item in artifacts]
    total = sum(sizes)
    return {
        "count": len(sizes),
        "totalBytes": total,
        "meanBytes": round(total / len(sizes), 1) if sizes else 0.0,
        "bytes": sizes,
    }


def run_record(
    result: dict[str, object],
    *,
    batch: int,
    e2e_ms: float,
    gpu_rates: dict[str, float],
) -> dict[str, object]:
    timing = dict(result.get("timing") or {})
    artifacts = [dict(item) for item in result.get("artifacts", []) if isinstance(item, dict)]
    gpu = str(timing.get("gpu") or "")
    gpu_class = canonical_gpu_name(gpu)
    if len(artifacts) != batch:
        raise RuntimeError(f"benchmark expected {batch} artifacts, got {len(artifacts)}")
    items = timing.get("items")
    if not isinstance(items, list) or len(items) != batch:
        raise RuntimeError(f"benchmark expected {batch} timing items")
    load_ms = timing.get("worker_load_ms")
    batch_ms = float(timing.get("batch_total_ms") or 0.0)
    gpu_ms = batch_ms + (float(load_ms) if load_ms is not None else 0.0)
    rate = gpu_rates.get(gpu_class)
    cost = None if rate is None else gpu_ms / 3_600_000 * rate
    return {
        "batch": batch,
        "e2eMs": round(e2e_ms, 3),
        "e2ePerImageMs": round(e2e_ms / batch, 3),
        "gpuClass": gpu_class,
        "gpuSeconds": round(gpu_ms / 1000, 4),
        "estimatedGpuCostUsd": None if cost is None else round(cost, 6),
        "estimatedGpuCostPerImageUsd": None if cost is None else round(cost / batch, 6),
        "artifacts": artifact_stats(artifacts),
        "timing": timing,
    }


def _model_map(capability: dict[str, object]) -> dict[str, dict[str, object]]:
    models = capability.get("models")
    if not isinstance(models, list):
        raise RuntimeError("modal-2D capability has no models")
    return {
        str(model["id"]): dict(model)
        for model in models
        if isinstance(model, dict) and isinstance(model.get("id"), str)
    }


def _benchmark_model(
    *,
    client,
    model: dict[str, object],
    batches: tuple[int, ...],
    prompt: str,
    seed: int,
    timeout: int,
    gpu_rates: dict[str, float],
) -> dict[str, object]:
    import modal

    route = model.get("generation_entrypoint")
    if not isinstance(route, dict):
        raise RuntimeError(f"model {model['id']} has no generation_entrypoint")
    worker = modal.Cls.from_name(
        str(route["app"]),
        str(route["class_name"]),
        client=client,
    )(model_id=str(model["id"]))
    method = getattr(worker, str(route["batch_generate_method"]))
    next_seed = seed

    def execute(batch: int) -> dict[str, object]:
        nonlocal next_seed
        seeds = list(range(next_seed, next_seed + batch))
        next_seed += batch
        payload = {"prompt": prompt, "model": model["id"], "seeds": seeds}
        started = perf_counter()
        call = method.spawn(payload)
        result = call.get(timeout=timeout)
        elapsed_ms = (perf_counter() - started) * 1000
        if not isinstance(result, dict):
            raise RuntimeError(f"model {model['id']} returned invalid benchmark result")
        return run_record(result, batch=batch, e2e_ms=elapsed_ms, gpu_rates=gpu_rates)

    cold_probe = execute(1)
    cold_timing = cold_probe["timing"]
    cold_probe["coldStartObserved"] = bool(
        cold_timing.get("worker_load_ms") is not None and cold_timing.get("worker_reused") is False
    )
    warm_runs = [execute(batch) for batch in batches]
    return {
        "model": {
            "id": model["id"],
            "name": model.get("name"),
            "profiles": model.get("profiles"),
            "worker": route,
        },
        "coldProbe": cold_probe,
        "warmRuns": warm_runs,
        "summary": _summary(warm_runs),
    }


def _summary(runs: list[dict[str, object]]) -> dict[str, object]:
    images = sum(int(run["batch"]) for run in runs)
    e2e_ms = sum(float(run["e2eMs"]) for run in runs)
    gpu_seconds = sum(float(run["gpuSeconds"]) for run in runs)
    return {
        "images": images,
        "e2eSeconds": round(e2e_ms / 1000, 3),
        "meanE2eMsPerImage": round(e2e_ms / images, 3) if images else 0.0,
        "gpuSeconds": round(gpu_seconds, 4),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark deployed modal-2D workers")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="model id; repeatable. Defaults to all advertised models",
    )
    parser.add_argument("--batches", default=",".join(map(str, DEFAULT_BATCHES)))
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--seed", type=int, default=10_000)
    parser.add_argument("--timeout", type=int, default=1800, help="seconds per remote batch call")
    parser.add_argument(
        "--gpu-rate",
        action="append",
        default=[],
        metavar="GPU=USD_PER_HOUR",
        help="optional rate used only for cost estimates; repeatable",
    )
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    import modal

    args = _parser().parse_args(argv)
    try:
        batches = parse_batches(args.batches)
        gpu_rates = parse_gpu_rates(args.gpu_rate)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    client = modal.Client.from_env()
    client.hello()
    capability = capabilities_document()
    available = _model_map(capability)
    selected = args.model or list(available)
    unknown = [model for model in selected if model not in available]
    if unknown:
        raise RuntimeError(f"unsupported benchmark models: {', '.join(unknown)}")

    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "provider": capability.get("provider"),
        "contract": capability.get("contract"),
        "prompt": args.prompt,
        "batches": list(batches),
        "gpuRatesUsdPerHour": gpu_rates,
        "results": [],
    }
    for model_id in selected:
        print(f"benchmarking {model_id} ...", file=sys.stderr, flush=True)
        report["results"].append(
            _benchmark_model(
                client=client,
                model=available[model_id],
                batches=batches,
                prompt=args.prompt,
                seed=args.seed,
                timeout=args.timeout,
                gpu_rates=gpu_rates,
            )
        )

    encoded = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0
