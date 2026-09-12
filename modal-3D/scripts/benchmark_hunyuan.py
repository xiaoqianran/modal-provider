from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import modal

from modal_3d.hunyuan2_1_plus_plus import APP_NAME
from modal_3d.hunyuan_benchmark import (
    CANONICAL_STATION_INPUT,
    FROZEN_QUALITY_OPTIONS,
    VARIANTS,
    get_variant,
    summarize_runs,
    validate_warmup,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a frozen-quality Hunyuan3D-2.1 acceleration A/B on Modal."
    )
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="base-official")
    parser.add_argument("--input-path", default=CANONICAL_STATION_INPUT)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--environment", default=None)
    parser.add_argument("--allow-unreleased", action="store_true")
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.runs <= 5:
        raise SystemExit("--runs must be between 1 and 5")

    variant = get_variant(args.variant, allow_unreleased=args.allow_unreleased)
    run_id = uuid.uuid4().hex
    variant_env = {**variant.env, "HUNYUAN_BENCHMARK_RUN_ID": run_id}

    lookup_kwargs = {}
    if args.environment:
        lookup_kwargs["environment_name"] = args.environment
    BaseModel = modal.Cls.from_name(APP_NAME, "Model", **lookup_kwargs)
    VariantModel = BaseModel.with_options(
        env=variant_env,
        max_containers=1,
        scaledown_window=300,
    )
    worker = VariantModel()

    cold_t0 = time.perf_counter()
    warmup = worker.warmup.remote()
    cold_warmup_client_s = time.perf_counter() - cold_t0
    validate_warmup(variant, warmup)

    records = []
    for index in range(args.runs):
        t0 = time.perf_counter()
        result = worker.generate_job.remote(args.input_path, dict(FROZEN_QUALITY_OPTIONS))
        records.append(
            {
                "index": index,
                "client_e2e_s": time.perf_counter() - t0,
                "result": result,
            }
        )

    payload = {
        "schema": "modal-3d.hunyuan21-perf-ab.v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "app": APP_NAME,
        "variant": variant.name,
        "variant_env": variant_env,
        "required_artifact": variant.requires_artifact,
        "input_path": args.input_path,
        "quality": dict(FROZEN_QUALITY_OPTIONS),
        "cold_warmup_client_s": cold_warmup_client_s,
        "warmup": warmup,
        "summary": summarize_runs(records),
        "runs": records,
    }

    if args.output:
        output = Path(args.output)
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = Path("benchmarks/runs") / f"hunyuan21-{variant.name}-{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2, ensure_ascii=False))
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
