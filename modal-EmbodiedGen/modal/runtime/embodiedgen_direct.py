"""Local/VPS control plane for the deployed EmbodiedGen Modal workers.

This module deliberately performs orchestration in the caller process.  It uses
Modal control-plane APIs to upload inputs, persist compact job state, update
worker autoscalers, and invoke the real compute workers directly.  It never
spawns a Modal gateway/orchestrator container.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import modal

APP_NAME = "modal-3d-embodiedgen"
AFFORDANCE_APP_NAME = "modal-3d-embodiedgen-affordance"
AFFORDANCE_SEMANTIC_APP_NAME = "modal-3d-embodiedgen-affordance-semantic"
ARTIFACT_VOLUME = "modal-3d-artifacts"
JOB_DICT = "modal-3d-embodiedgen-jobs"
TRAFFIC_DICT = "modal-3d-embodiedgen-traffic"
JOB_PREFIX = "job-"
JOB_VOLUME_PREFIX = "/embodiedgen/jobs"

COMPAT_PROFILES = {"auto", "warm", "min_cost", "cost_first", "balanced", "burst"}
PIPELINE_POLICY = "warm_180"
TEXT2IMG_POLICY = "handoff_5"
RETEXTURE_POLICY = "warm_120"
RESULT_FILES = {
    "glb": "result/mesh/sample_00.glb",
    "obj": "result/mesh/sample_00.obj",
    "mtl": "result/mesh/material.mtl",
    "obj_texture": "result/mesh/material_0.png",
    "urdf": "result/sample_00.urdf",
    "video": "result/video.mp4",
    "validation": "validation_report.json",
}


def new_job_id() -> str:
    return f"{JOB_PREFIX}{uuid.uuid4().hex}"


def _stamp(state: dict) -> dict:
    now = time.time()
    state["updated_epoch"] = now
    state["updated_at"] = datetime.fromtimestamp(now, UTC).isoformat()
    return state


def _jobs():
    return modal.Dict.from_name(JOB_DICT, create_if_missing=True)


def _artifacts():
    return modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=False)


def get_job(job_id: str) -> dict | None:
    return _jobs().get(job_id)


def list_jobs(limit: int = 100) -> list[dict]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    jobs = [dict(state or {"job_id": job_id}) for job_id, state in _jobs().items()]
    jobs.sort(key=lambda state: float(state.get("created_epoch", 0) or 0), reverse=True)
    return jobs[:limit]


def _put_job(job_id: str, **changes) -> dict:
    jobs = _jobs()
    state = dict(jobs.get(job_id) or {"job_id": job_id})
    state.update(changes)
    _stamp(state)
    jobs.put(job_id, state)
    return state


def _compat_profile(requested: str) -> str:
    """Validate the old UI argument, but routing is now deployment-static."""
    if requested not in COMPAT_PROFILES:
        raise ValueError(f"unknown profile: {requested}")
    return PIPELINE_POLICY


def _new_job(*, workflow: str, requested_profile: str, input_info: dict) -> str:
    job_id = new_job_id()
    now = time.time()
    _jobs().put(job_id, {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "workflow": workflow,
        "profile": PIPELINE_POLICY,
        "requested_profile": requested_profile,
        "runtime_policy": PIPELINE_POLICY,
        "created_epoch": now,
        "created_at": datetime.fromtimestamp(now, UTC).isoformat(),
        "updated_epoch": now,
        "updated_at": datetime.fromtimestamp(now, UTC).isoformat(),
        "input": input_info,
    })
    return job_id


def _pipeline_worker():
    return modal.Cls.from_name(APP_NAME, "EmbodiedGenWorker")()


def submit_image3d(image_path: str | Path, profile: str = "auto", *, seed: int = 0) -> dict:
    """Read/validate locally, then spawn one unified L40S pipeline and return immediately."""
    _compat_profile(profile)
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size <= 0 or size > 20 * 1024 * 1024:
        raise ValueError("image must contain 1 byte..20 MiB")
    data = path.read_bytes()
    job_id = _new_job(
        workflow="image_to_3d",
        requested_profile=profile,
        input_info={"type": "image", "bytes": size, "name": path.name},
    )
    try:
        call = _pipeline_worker().generate.spawn(job_id, data, int(seed))
        return _put_job(
            job_id,
            status="queued",
            stage="gpu_dispatch",
            modal_call_id=getattr(call, "object_id", None),
        )
    except Exception as exc:
        _put_job(job_id, status="failed", stage="gpu_dispatch", error_type=type(exc).__name__, error=str(exc)[:2000])
        raise


def _wait_job(job_id: str, timeout: float = 30 * 60, poll: float = 1.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = get_job(job_id)
        if state and state.get("status") in {"succeeded", "failed"}:
            if state.get("status") == "failed":
                raise RuntimeError(state.get("error") or f"job failed at {state.get('stage')}")
            return state
        time.sleep(poll)
    raise TimeoutError(f"job timed out: {job_id}")


def generate_image3d(image_path: str | Path, profile: str = "auto") -> dict:
    """Synchronous compatibility wrapper around submit_image3d()."""
    state = submit_image3d(image_path, profile)
    return _wait_job(state["job_id"])


def submit_text3d(prompt: str, seed: int = 0, profile: str = "auto") -> dict:
    """Spawn Kolors immediately; Kolors dispatches PNG bytes directly to unified GPU worker."""
    _compat_profile(profile)
    prompt = str(prompt).strip()
    if not prompt or len(prompt) > 1000:
        raise ValueError("prompt must contain 1..1000 characters")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 100000:
        raise ValueError("seed must be an integer in 0..100000")
    job_id = _new_job(
        workflow="text_to_3d",
        requested_profile=profile,
        input_info={"type": "text", "prompt_chars": len(prompt), "seed": seed},
    )
    _put_job(job_id, runtime_policy=f"{TEXT2IMG_POLICY}+{PIPELINE_POLICY}", stage="text2image")
    try:
        text = modal.Cls.from_name(APP_NAME, "Text2ImageWorker")()
        call = text.generate.spawn(job_id, prompt, seed, True)
        return _put_job(job_id, status="queued", stage="text2image", modal_text_call_id=getattr(call, "object_id", None))
    except Exception as exc:
        _put_job(job_id, status="failed", stage="text2image", error_type=type(exc).__name__, error=str(exc)[:2000])
        raise


def generate_text3d(prompt: str, seed: int = 0, profile: str = "auto") -> dict:
    """Synchronous compatibility wrapper around submit_text3d()."""
    state = submit_text3d(prompt, seed, profile)
    return _wait_job(state["job_id"])


def retexture(source_job_id: str, prompt: str, seed: int = 0, profile: str = "auto") -> dict:
    """Retexture keeps its own warm GPU model; autoscaling is fixed at deployment time."""
    _compat_profile(profile)
    source = get_job(source_job_id)
    if not source or source.get("status") != "succeeded":
        raise ValueError("source job must exist and be succeeded")
    prompt = str(prompt).strip()
    if not prompt or len(prompt) > 1000:
        raise ValueError("prompt must contain 1..1000 characters")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 100000:
        raise ValueError("seed must be an integer in 0..100000")
    job_id = _new_job(
        workflow="retexture",
        requested_profile=profile,
        input_info={"type": "retexture", "source_job_id": source_job_id, "seed": seed},
    )
    _put_job(job_id, profile=RETEXTURE_POLICY, runtime_policy=RETEXTURE_POLICY, source_job_id=source_job_id)
    worker = modal.Cls.from_name(APP_NAME, "RetextureWorker")()
    started = time.perf_counter()
    try:
        _put_job(job_id, status="running", stage="retexture")
        validation = worker.generate.remote(job_id, source_job_id, prompt, seed)
        elapsed = round(time.perf_counter() - started, 3)
        return _put_job(job_id, status="succeeded", stage="done", stage_seconds={"retexture": elapsed}, files=sorted(RESULT_FILES), validation=validation)
    except Exception as exc:
        elapsed = round(time.perf_counter() - started, 3)
        _put_job(job_id, status="failed", stage="retexture", stage_seconds={"retexture": elapsed}, error_type=type(exc).__name__, error=str(exc)[:2000])
        raise


AFFORDANCE_PROFILE = "part-evidence-only"
AFFORDANCE_SEMANTIC_PROFILE = "semantic-evidence-v1"
AFFORDANCE_DEFAULTS = {
    "point_num": 20000,
    "prompt_num": 64,
    "prompt_bs": 8,
    "grasp_num_points": 2024,
    "num_grasps": 80,
    "topk": 20,
    "seed": 42,
}
AFFORDANCE_RESULT_FILES = {
    "source_glb": "source/sample_00.glb",
    "source_urdf": "source/sample_00.urdf",
    "part_segmentation": "affordance/agentscape_part_segmentation.v1.json",
    "raw_grasps": "affordance/raw_grasps.franka.v1.json",
    "segment_validation": "affordance/validation_report.json",
    "grasp_validation": "affordance/graspgen_validation_report.json",
    "affordance_bundle": "affordance/bundle.v1.json",
    "affordance_validation": "validation_report.json",
}
AFFORDANCE_SEMANTIC_RESULT_FILES = {
    "semantic_inputs": "affordance/semantic_inputs/semantic_inputs.v1.json",
    "semantic_rgb_grid": "affordance/semantic_inputs/rgb_grid.png",
    "semantic_mask_grid": "affordance/semantic_inputs/mask_grid.png",
    "semantic_part_atlas": "affordance/semantic_inputs/part_atlas.png",
    "part_semantics": "affordance/part_semantics.v1.json",
    "semantic_validation": "affordance/semantic_validation_report.json",
}


def normalize_affordance_options(payload: dict | None) -> dict:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise TypeError("affordance payload must be an object")
    allowed = {
        "profile", "point_num", "prompt_num", "prompt_bs", "grasp_num_points",
        "num_grasps", "topk", "seed", "category",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unsupported affordance options: {unknown}")
    profile = payload.get("profile", AFFORDANCE_PROFILE)
    if profile not in {AFFORDANCE_PROFILE, AFFORDANCE_SEMANTIC_PROFILE}:
        raise ValueError(f"unsupported affordance profile: {profile!r}")
    if profile == AFFORDANCE_PROFILE and "category" in payload:
        raise ValueError("category is only supported by semantic-evidence-v1")
    options = {"profile": profile, **AFFORDANCE_DEFAULTS}
    for key in AFFORDANCE_DEFAULTS:
        if key in payload:
            options[key] = payload[key]
    if profile == AFFORDANCE_SEMANTIC_PROFILE:
        category = str(payload.get("category") or "unknown object").strip()
        if not category or len(category) > 160:
            raise ValueError("category must contain 1..160 characters")
        options["category"] = category
    for key in (
        "point_num", "prompt_num", "prompt_bs", "grasp_num_points",
        "num_grasps", "topk", "seed",
    ):
        value = options[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{key} must be an integer")
    if not 1000 <= options["point_num"] <= 200000:
        raise ValueError("point_num must be in 1000..200000")
    if not 8 <= options["prompt_num"] <= 800:
        raise ValueError("prompt_num must be in 8..800")
    if not 1 <= options["prompt_bs"] <= 64:
        raise ValueError("prompt_bs must be in 1..64")
    if not 512 <= options["grasp_num_points"] <= 20000:
        raise ValueError("grasp_num_points must be in 512..20000")
    if not 1 <= options["num_grasps"] <= 1000:
        raise ValueError("num_grasps must be in 1..1000")
    if not 1 <= options["topk"] <= min(options["num_grasps"], 200):
        raise ValueError("topk must be in 1..min(num_grasps, 200)")
    if not 0 <= options["seed"] <= 2**31 - 1:
        raise ValueError("seed must be a non-negative 32-bit integer")
    return options


def generate_affordance(source_job_id: str, payload: dict | None = None) -> dict:
    source = get_job(source_job_id)
    if not source or source.get("status") != "succeeded":
        raise ValueError("source job must exist and be succeeded")
    options = normalize_affordance_options(payload)
    profile = options["profile"]
    job_id = new_job_id()
    now = time.time()
    _jobs().put(
        job_id,
        _stamp(
            {
                "job_id": job_id,
                "status": "queued",
                "stage": "queued",
                "profile": profile,
                "workflow": "asset.affordance",
                "source_job_id": source_job_id,
                "created_epoch": now,
                "created_at": datetime.fromtimestamp(now, UTC).isoformat(),
                "input": {"type": "affordance", "source_job_id": source_job_id, "options": options},
            }
        ),
    )

    segment = modal.Function.from_name(AFFORDANCE_APP_NAME, "segment_job")
    grasp = modal.Function.from_name(AFFORDANCE_APP_NAME, "raw_grasp_job")
    semantic_inputs = modal.Function.from_name(APP_NAME, "prepare_affordance_semantic_inputs")
    semantic = modal.Function.from_name(AFFORDANCE_SEMANTIC_APP_NAME, "annotate_semantics")
    finalize = modal.Function.from_name(APP_NAME, "finalize_affordance_bundle")
    timings: dict[str, float] = {}

    _run_stage(
        job_id,
        "segment",
        lambda: segment.remote(
            source_job_id,
            point_num=options["point_num"],
            prompt_num=options["prompt_num"],
            prompt_bs=options["prompt_bs"],
            output_job_id=job_id,
        ),
        timings,
    )
    _run_stage(
        job_id,
        "grasp_raw",
        lambda: grasp.remote(
            source_job_id,
            num_points=options["grasp_num_points"],
            num_grasps=options["num_grasps"],
            topk=options["topk"],
            seed=options["seed"],
            output_job_id=job_id,
        ),
        timings,
    )
    if profile == AFFORDANCE_SEMANTIC_PROFILE:
        _run_stage(
            job_id,
            "semantic_inputs",
            lambda: semantic_inputs.remote(job_id, options["category"]),
            timings,
        )
        _run_stage(job_id, "semantic_annotate", lambda: semantic.remote(job_id), timings)

    validation = _run_stage(
        job_id,
        "finalize",
        lambda: finalize.remote(job_id, source_job_id, options),
        timings,
    )
    files = dict(AFFORDANCE_RESULT_FILES)
    if profile == AFFORDANCE_SEMANTIC_PROFILE:
        files.update(AFFORDANCE_SEMANTIC_RESULT_FILES)
    return _put_job(
        job_id,
        status="succeeded",
        stage="done",
        profile=profile,
        workflow="asset.affordance",
        source_job_id=source_job_id,
        options=options,
        stage_seconds=timings,
        files=sorted(files),
        validation=validation,
    )


def download_result(job_id: str, name: str, destination: str | Path) -> Path:
    state = get_job(job_id)
    if not state or state.get("status") != "succeeded":
        raise ValueError("job must exist and be succeeded")
    if name not in (state.get("files") or []):
        raise ValueError(f"result is not available for this job: {name}")

    paths = {**RESULT_FILES, **AFFORDANCE_RESULT_FILES, **AFFORDANCE_SEMANTIC_RESULT_FILES}
    if name not in paths:
        raise ValueError(f"unknown result name: {name}")
    remote = f"{JOB_VOLUME_PREFIX}/{job_id}/{paths[name]}"
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as stream:
        for chunk in _artifacts().read_file(remote):
            stream.write(chunk)
    return destination
