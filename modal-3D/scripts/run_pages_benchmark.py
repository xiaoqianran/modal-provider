from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.benchmark_runner import (
    assert_deployed_matches,
    build_plan,
    load_manifest,
    recommended_profile,
    recover_task_id,
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
    """Atomically persist task IDs before the caller can lose process state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def _load_state(path: Path, plan: dict, schema: str) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    state = json.loads(path.read_text())
    if state.get("schema") != schema:
        raise ValueError("benchmark state schema is not supported")
    if state.get("plan") != plan:
        raise ValueError("existing benchmark state does not match the current plan")
    return state


def _new_smoke_state(plan: dict) -> dict:
    return {
        "schema": "modal-3d.benchmark-smoke.v1",
        "plan": plan,
        "started_at": time.time(),
        "models": {},
    }


def _verify_remote_inputs(scenes) -> None:
    import hashlib
    import modal

    volume = modal.Volume.from_name("modal-3d-artifacts")
    for scene in scenes:
        digest = hashlib.sha256()
        found = False
        try:
            for chunk in volume.read_file(scene.modal_path):
                found = True
                digest.update(chunk)
        except FileNotFoundError as exc:
            raise ValueError(f"{scene.id}: canonical input is missing from modal-3d-artifacts") from exc
        if not found or digest.hexdigest() != scene.sha256:
            raise ValueError(f"{scene.id}: Modal Volume input SHA256 does not match local canonical")


def _deployed_capabilities(local_capabilities: list[dict], model_ids: list[str]) -> dict[str, dict]:
    import modal

    gateway_caps = modal.Function.from_name("modal-3d-gateway", "capabilities").remote()
    deployed_by_id = {item["id"]: item for item in gateway_caps["models"]}
    local_by_id = {item["id"]: item for item in local_capabilities}
    for model_id in model_ids:
        deployed = deployed_by_id.get(model_id)
        if deployed is None:
            raise RuntimeError(f"{model_id}: not advertised by deployed gateway")
        assert_deployed_matches(local_by_id[model_id], deployed)
    return local_by_id


def _mark_submission_intent(model_state: dict, scene, options: dict) -> None:
    model_state.update(
        {
            "status": "submitting",
            "scene": scene.id,
            "modal_path": scene.modal_path,
            "input_sha256": scene.sha256,
            "options": options,
            "intent_at": time.time(),
        }
    )


def _recover_submission(model_id: str, model_state: dict) -> bool:
    import modal

    if model_state.get("status") != "submitting":
        return False
    intent_at = model_state.get("intent_at")
    if not isinstance(intent_at, (int, float)):
        raise ValueError(f"{model_id}: submitting state is missing intent_at")
    job_keys = modal.Dict.from_name("modal-3d-job-keys", create_if_missing=False)
    tasks = modal.Dict.from_name("modal-3d-tasks", create_if_missing=False)
    task_id = recover_task_id(
        model_id,
        model_state["modal_path"],
        model_state["options"],
        job_keys,
        tasks,
        intent_at=float(intent_at),
    )
    if task_id is None:
        return False
    model_state["task_id"] = task_id
    model_state["status"] = "submitted"
    model_state["recovered"] = True
    return True


def _submit_one(submit, model_id: str, scene, options: dict, model_state: dict, state: dict, state_path: Path) -> None:
    _mark_submission_intent(model_state, scene, options)
    _save(state_path, state)
    try:
        record = submit.remote(model_id, scene.modal_path, options)
    except Exception as exc:
        model_state["submit_error"] = {"type": type(exc).__name__, "message": str(exc)}
        _save(state_path, state)
        raise RuntimeError(
            f"{model_id}: submission outcome is uncertain; poll/resume to recover before retrying"
        ) from exc
    model_state.update(
        {
            "status": "submitted",
            "task_id": record["task_id"],
            "submitted_at": record.get("submitted_at", time.time()),
            "deduplicated": bool(record.get("deduplicated")),
        }
    )
    model_state.pop("submit_error", None)
    _save(state_path, state)


def _submit_smoke(args, scenes, local_capabilities, model_ids, plan) -> None:
    """Submit at most one scene per model and persist each FunctionCall ID immediately."""
    import modal

    local_by_id = _deployed_capabilities(local_capabilities, model_ids)
    submit = modal.Function.from_name("modal-3d-gateway", "submit")
    state = (
        _load_state(args.state, plan, "modal-3d.benchmark-smoke.v1")
        if args.state.exists()
        else _new_smoke_state(plan)
    )
    scene = scenes[0]
    _verify_remote_inputs([scene])

    for model_id in model_ids:
        existing = state["models"].get(model_id)
        if isinstance(existing, dict) and existing.get("task_id"):
            continue
        options = dict(recommended_profile(local_by_id[model_id])["options"])
        model_state: dict = {}
        state["models"][model_id] = model_state
        _submit_one(submit, model_id, scene, options, model_state, state, args.state)

    print(json.dumps(state, indent=2, ensure_ascii=False))
    print(f"SMOKE SUBMITTED: state persisted at {args.state}; use --resume to poll without submitting new jobs")


def _poll_task(model_state: dict) -> None:
    import modal

    task_id = model_state.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("submitted benchmark state is missing task_id")
    try:
        result = modal.functions.FunctionCall.from_id(task_id).get(timeout=0)
    except TimeoutError:
        model_state["status"] = "running"
    except Exception as exc:
        model_state.update(
            {
                "status": "failed",
                "finished_at": time.time(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
    else:
        model_state.update(
            {
                "status": "completed",
                "finished_at": time.time(),
                "result": result,
            }
        )


def _resume_smoke(args, plan) -> None:
    state = _load_state(args.state, plan, "modal-3d.benchmark-smoke.v1")
    if not state["models"]:
        raise ValueError("benchmark state contains no submitted jobs")

    for model_id, model_state in state["models"].items():
        if model_state.get("status") in {"completed", "failed"}:
            continue
        if model_state.get("status") == "submitting" and not _recover_submission(model_id, model_state):
            _save(args.state, state)
            continue
        _poll_task(model_state)
        _save(args.state, state)

    if all(item.get("status") in {"completed", "failed"} for item in state["models"].values()):
        state["finished_at"] = time.time()
        _save(args.state, state)
    print(json.dumps(state, indent=2, ensure_ascii=False))


def _validated_smoke_state(path: Path, scenes, local_by_id, model_ids) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    smoke = json.loads(path.read_text())
    if smoke.get("schema") != "modal-3d.benchmark-smoke.v1":
        raise ValueError("--smoke-state has unsupported schema")
    if set(smoke.get("models", {})) != set(model_ids):
        raise ValueError("--smoke-state model set does not match the full plan")
    first_scene = scenes[0].id
    for model_id in model_ids:
        entry = smoke["models"][model_id]
        if entry.get("status") != "completed" or not isinstance(entry.get("result"), dict):
            raise ValueError(f"{model_id}: smoke must be completed successfully before full execution")
        if entry.get("scene") != first_scene:
            raise ValueError(f"{model_id}: smoke scene does not match current manifest")
        if entry.get("modal_path") != scenes[0].modal_path or entry.get("input_sha256") != scenes[0].sha256:
            raise ValueError(f"{model_id}: smoke input identity does not match current manifest")
        expected = recommended_profile(local_by_id[model_id])["options"]
        if entry.get("options") != expected:
            raise ValueError(f"{model_id}: smoke options do not match current recommended profile")
        if entry["result"].get("model") != model_id:
            raise ValueError(f"{model_id}: smoke result model mismatch")
    return smoke


def _new_full_state(plan: dict, smoke: dict, scenes, model_ids) -> dict:
    state = {
        "schema": "modal-3d.benchmark-full.v1",
        "plan": plan,
        "started_at": time.time(),
        "models": {},
    }
    for model_id in model_ids:
        smoke_entry = smoke["models"][model_id]
        state["models"][model_id] = {
            "status": "ready" if len(scenes) > 1 else "completed",
            "next_scene_index": 1,
            "results": [
                {
                    "scene": smoke_entry["scene"],
                    "modal_path": smoke_entry["modal_path"],
                    "input_sha256": smoke_entry["input_sha256"],
                    "task_id": smoke_entry["task_id"],
                    "options": smoke_entry["options"],
                    "result": smoke_entry["result"],
                    "source": "smoke-state",
                }
            ],
        }
    return state


def _submit_full_round(args, scenes, local_capabilities, model_ids, plan) -> None:
    import modal

    local_by_id = _deployed_capabilities(local_capabilities, model_ids)
    submit = modal.Function.from_name("modal-3d-gateway", "submit")
    if args.state.exists():
        state = _load_state(args.state, plan, "modal-3d.benchmark-full.v1")
    else:
        if args.smoke_state is None:
            raise ValueError("first paid --full execution requires --smoke-state")
        smoke = _validated_smoke_state(args.smoke_state, scenes, local_by_id, model_ids)
        state = _new_full_state(plan, smoke, scenes, model_ids)
        _save(args.state, state)

    pending_scenes = {
        int(state["models"][model_id].get("next_scene_index", 1))
        for model_id in model_ids
        if state["models"][model_id].get("status") == "ready"
    }
    _verify_remote_inputs([scenes[index] for index in sorted(pending_scenes) if index < len(scenes)])

    submitted = 0
    for model_id in model_ids:
        model_state = state["models"][model_id]
        if model_state.get("status") != "ready":
            continue
        index = int(model_state.get("next_scene_index", 1))
        if index >= len(scenes):
            model_state["status"] = "completed"
            _save(args.state, state)
            continue
        scene = scenes[index]
        options = dict(recommended_profile(local_by_id[model_id])["options"])
        _submit_one(submit, model_id, scene, options, model_state, state, args.state)
        submitted += 1
    print(json.dumps(state, indent=2, ensure_ascii=False))
    print(f"FULL ROUND SUBMITTED: {submitted} jobs; poll with --resume --full before --advance --full")


def _resume_full(args, scenes, plan) -> None:
    state = _load_state(args.state, plan, "modal-3d.benchmark-full.v1")
    for model_id, model_state in state["models"].items():
        if model_state.get("status") == "submitting" and not _recover_submission(model_id, model_state):
            _save(args.state, state)
            continue
        if model_state.get("status") not in {"submitted", "running"}:
            continue
        _poll_task(model_state)
        if model_state["status"] == "completed":
            model_state["results"].append(
                {
                    "scene": model_state.pop("scene"),
                    "modal_path": model_state.pop("modal_path"),
                    "input_sha256": model_state.pop("input_sha256"),
                    "task_id": model_state.pop("task_id"),
                    "options": model_state.pop("options"),
                    "result": model_state.pop("result"),
                    "source": "full-run",
                }
            )
            model_state.pop("submitted_at", None)
            model_state.pop("finished_at", None)
            model_state.pop("deduplicated", None)
            model_state["next_scene_index"] = int(model_state["next_scene_index"]) + 1
            model_state["status"] = (
                "completed" if model_state["next_scene_index"] >= len(scenes) else "ready"
            )
        _save(args.state, state)

    if all(item.get("status") in {"completed", "failed"} for item in state["models"].values()):
        state["finished_at"] = time.time()
        _save(args.state, state)
    print(json.dumps(state, indent=2, ensure_ascii=False))


def _advance_full(args, scenes, local_capabilities, model_ids, plan) -> None:
    state = _load_state(args.state, plan, "modal-3d.benchmark-full.v1")
    if any(item.get("status") in {"submitting", "submitted", "running"} for item in state["models"].values()):
        raise ValueError("cannot advance while the previous full round is unresolved; poll with --resume --full")
    if all(item.get("status") in {"completed", "failed"} for item in state["models"].values()):
        print(json.dumps(state, indent=2, ensure_ascii=False))
        print("FULL MATRIX TERMINAL: no further jobs were submitted")
        return
    _submit_full_round(args, scenes, local_capabilities, model_ids, plan)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cost-guarded Pages benchmark. Dry-run by default; paid execution starts with smoke only."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--models", default=",".join(MODEL_IDS))
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--execute", action="store_true", help="submit smoke, or initialize the first full round")
    actions.add_argument("--resume", action="store_true", help="poll persisted tasks; never submits")
    actions.add_argument("--advance", action="store_true", help="submit one next full-matrix round after polling")
    parser.add_argument("--full", action="store_true", help="plan/execute the full matrix after a successful smoke")
    parser.add_argument("--smoke-state", type=Path, help="completed smoke state required to initialize full execution")
    parser.add_argument("--max-calls", type=int, default=4)
    parser.add_argument("--max-estimated-gpu-seconds", type=float, default=1500.0)
    parser.add_argument("--state", type=Path, default=Path("benchmarks/.pages-benchmark-state.json"))
    args = parser.parse_args()

    if args.advance and not args.full:
        parser.error("--advance requires --full")

    model_ids = [item for item in args.models.split(",") if item]
    if not model_ids or len(model_ids) != len(set(model_ids)):
        parser.error("--models must contain unique model ids")

    try:
        scenes = load_manifest(args.manifest)
        local_capabilities = _local_capabilities()
        plan = build_plan(local_capabilities, scenes, model_ids, full=args.full)
        validate_budget(
            plan,
            max_calls=args.max_calls,
            max_estimated_gpu_seconds=args.max_estimated_gpu_seconds,
        )
        if args.resume:
            if args.full:
                _resume_full(args, scenes, plan)
            else:
                _resume_smoke(args, plan)
            return
        if args.advance:
            _advance_full(args, scenes, local_capabilities, model_ids, plan)
            return
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        if not args.execute:
            print("DRY RUN: no Modal GPU jobs were submitted")
            return
        if args.full:
            _submit_full_round(args, scenes, local_capabilities, model_ids, plan)
        else:
            _submit_smoke(args, scenes, local_capabilities, model_ids, plan)
    except (FileNotFoundError, RuntimeError, TypeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
