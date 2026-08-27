from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.benchmark_runner import (
    assert_deployed_matches,
    build_plan,
    load_manifest,
    recommended_profile,
    validate_budget,
)

MODEL_IDS = [
    "fastsam3d-plus-plus",
    "hunyuan2.1-plus-plus",
    "hermit-trellis2-plus-plus",
    "pixal3d",
]


def _local_capabilities() -> list[dict]:
    from modal_3d.fastsam3d_plus_plus import CAPABILITY as fastsam
    from modal_3d.hermit_trellis2_plus_plus import CAPABILITY as hermit
    from modal_3d.hunyuan2_1_plus_plus import CAPABILITY as hunyuan
    from modal_3d.pixal3d import CAPABILITY as pixal

    return [fastsam, hunyuan, hermit, pixal]


def _save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def _execute(args, scenes, local_capabilities, model_ids, plan) -> None:
    import modal

    gateway_caps = modal.Function.from_name("modal-3d-gateway", "capabilities").remote()
    deployed_by_id = {item["id"]: item for item in gateway_caps["models"]}
    local_by_id = {item["id"]: item for item in local_capabilities}
    for model_id in model_ids:
        deployed = deployed_by_id.get(model_id)
        if deployed is None:
            raise RuntimeError(f"{model_id}: not advertised by deployed gateway")
        assert_deployed_matches(local_by_id[model_id], deployed)

    submit = modal.Function.from_name("modal-3d-gateway", "submit")
    state = {
        "plan": plan,
        "started_at": time.time(),
        "models": {},
    }
    _save(args.state, state)

    def run_model(model_id: str) -> dict:
        capability = local_by_id[model_id]
        options = dict(recommended_profile(capability)["options"])
        model_state = {"status": "running", "results": []}
        sequence = scenes if args.full else scenes[:1]
        for index, scene in enumerate(sequence):
            started = time.perf_counter()
            record = submit.remote(model_id, scene.modal_path, options)
            call = modal.functions.FunctionCall.from_id(record["task_id"])
            try:
                result = call.get(timeout=args.result_timeout)
            except Exception as exc:
                model_state["status"] = "failed"
                model_state["results"].append(
                    {
                        "scene": scene.id,
                        "task_id": record["task_id"],
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                        "wall_s": time.perf_counter() - started,
                    }
                )
                # Circuit breaker: never submit later scenes after one failure.
                break
            model_state["results"].append(
                {
                    "scene": scene.id,
                    "task_id": record["task_id"],
                    "wall_s": time.perf_counter() - started,
                    "result": result,
                }
            )
            # The first scene is always the smoke. Full mode continues only after it succeeds.
            if index == 0:
                model_state["smoke_passed"] = True
        else:
            model_state["status"] = "completed"
        return model_state

    with ThreadPoolExecutor(max_workers=len(model_ids)) as executor:
        futures = {executor.submit(run_model, model_id): model_id for model_id in model_ids}
        for future in as_completed(futures):
            model_id = futures[future]
            try:
                state["models"][model_id] = future.result()
            except Exception as exc:
                state["models"][model_id] = {
                    "status": "failed",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "results": [],
                }
            _save(args.state, state)
    state["finished_at"] = time.time()
    _save(args.state, state)
    print(json.dumps(state, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cost-guarded Pages benchmark. Dry-run by default; smoke-only unless --full is explicit."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--models", default=",".join(MODEL_IDS))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--max-calls", type=int, default=4)
    parser.add_argument("--max-estimated-gpu-seconds", type=float, default=1500.0)
    parser.add_argument("--result-timeout", type=float, default=1800.0)
    parser.add_argument("--state", type=Path, default=Path("benchmarks/.pages-benchmark-state.json"))
    args = parser.parse_args()

    model_ids = [item for item in args.models.split(",") if item]
    if not model_ids or len(model_ids) != len(set(model_ids)):
        raise SystemExit("--models must contain unique model ids")

    try:
        scenes = load_manifest(args.manifest)
        local_capabilities = _local_capabilities()
        plan = build_plan(local_capabilities, scenes, model_ids, full=args.full)
        validate_budget(
            plan,
            max_calls=args.max_calls,
            max_estimated_gpu_seconds=args.max_estimated_gpu_seconds,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    if not args.execute:
        print("DRY RUN: no Modal GPU jobs were submitted")
        return
    _execute(args, scenes, local_capabilities, model_ids, plan)


if __name__ == "__main__":
    main()
