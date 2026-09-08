from __future__ import annotations

import os

import modal

from .hyworld2_runtime import GPU, HYWORLD2_REVISION, hyworld2_worldgen_stage5_image
from .stage45_core import (
    assert_stage5_static_cache,
    run_stage4_core,
    run_stage5_core,
    run_stage5_smoke_core,
)
from .worldgen_job import (
    build_stage_manifest,
    fingerprint_files,
    resolve_worldgen_job_root,
    stage_manifest_path,
    stage_profile_file,
    stage_profile_name,
    write_stage_manifest,
)

app = modal.App("modal-world-stage45")
model_cache = modal.Volume.from_name("hyworld2-models", create_if_missing=True)
runtime_cache = modal.Volume.from_name(
    "hyworld2-runtime-cache-v2", create_if_missing=True, version=2
)
worldgen_outputs = modal.Volume.from_name("hyworld2-worldgen-output", create_if_missing=True)
hf_secret = modal.Secret.from_name(os.environ.get("MODAL_WORLD_HF_SECRET", "hyworld2-hf"))


@app.function(
    image=hyworld2_worldgen_stage5_image,
    gpu=GPU,
    cpu=16.0,
    memory=65536,
    volumes={
        "/models": model_cache.with_mount_options(read_only=True),
        "/runtime-cache": runtime_cache,
        "/worldgen": worldgen_outputs,
    },
    secrets=[hf_secret],
    timeout=3 * 60 * 60,
)
def worldgen_case000_stage45_rtx6000(
    job_id: str = "case000",
    force: bool = False,
    steps: int = 8000,
    export_mesh: bool = True,
) -> dict:
    """Run GS data preparation and 3DGS training in one RTX PRO 6000 container."""
    import json
    import time

    steps = int(steps)
    if steps <= 0:
        raise ValueError("steps must be > 0")

    # Synchronize Stage 3 exactly once. There is intentionally no reload between
    # run_stage4_core() and run_stage5_core().
    worldgen_outputs.reload()
    target = resolve_worldgen_job_root(job_id)
    stage45_stage = stage_profile_name("stage45", steps)
    stage5_stage = stage_profile_name("stage5", steps)
    log_path = stage_profile_file(target, "stage45", steps, ".log")
    timing_path = stage_profile_file(target, "stage45", steps, "_timing.json")

    # Fail before spending Stage 4 time if the static Stage 5 LPIPS cache was not
    # preflighted into the read-only model volume.
    assert_stage5_static_cache()

    total_started = time.perf_counter()
    with log_path.open("w") as log:
        log.write(f"stage45 start steps={steps} export_mesh={bool(export_mesh)}\n")
        log.flush()

        stage4_started = time.perf_counter()
        stage4 = run_stage4_core(
            job_id=job_id,
            force=bool(force),
            # Stage 5 consumes the same mounted files immediately. Avoid a
            # synchronous intermediate Volume commit on the success path; the
            # aggregate Stage45 commit below persists Stage4 + Stage5 together.
            commit_worldgen=None,
            commit_failure_worldgen=worldgen_outputs.commit,
            defer_stale_cleanup=True,
        )
        stage4_wall_s = time.perf_counter() - stage4_started
        log.write(f"stage4 complete wall_s={stage4_wall_s:.3f}\n")
        log.flush()

        # If Stage 4 replaced an older dataset, delete that stale tree while the
        # GPU trains on the newly promoted gs_data. This hides the expensive
        # recursive Volume deletion behind Stage 5 instead of serializing it.
        stale_cleanup = None
        stale_data_dir = stage4.get("stale_data_dir")
        if stale_data_dir:
            import shutil
            import threading

            stale_cleanup = threading.Thread(
                target=shutil.rmtree,
                args=(stale_data_dir,),
                kwargs={"ignore_errors": True},
                daemon=True,
            )
            stale_cleanup.start()

        # Stage 5 consumes the same mounted files immediately without a reload.
        stage5_started = time.perf_counter()
        try:
            stage5 = run_stage5_core(
                job_id=job_id,
                force=bool(force),
                steps=steps,
                export_mesh=bool(export_mesh),
                # Defer successful worldgen persistence to the aggregate
                # Stage45 commit so the same tree is synchronized only once.
                commit_worldgen=None,
                commit_failure_worldgen=worldgen_outputs.commit,
                commit_runtime_cache=runtime_cache.commit,
            )
        except Exception:
            if stale_cleanup is not None:
                stale_cleanup.join()
                # Persist the stale-tree cleanup after Stage5's diagnostic commit.
                worldgen_outputs.commit()
            raise
        if stale_cleanup is not None:
            stale_cleanup.join()
        stage5_wall_s = time.perf_counter() - stage5_started
        log.write(f"stage5 complete wall_s={stage5_wall_s:.3f}\n")
        log.flush()

    stage45_s = time.perf_counter() - total_started
    peaks = [
        value
        for value in (
            stage4.get("gpu_peak_used_mib"),
            stage5.get("gpu_peak_used_mib"),
        )
        if isinstance(value, (int, float))
    ]
    timing = {
        "steps": steps,
        "export_mesh": bool(export_mesh),
        "stage4_s": round(stage4_wall_s, 3),
        "stage5_s": round(stage5_wall_s, 3),
        "stage45_s": round(stage45_s, 3),
        "gpu_peak_used_mib": max(peaks) if peaks else None,
        "stage4_resumed": bool(stage4.get("resumed")),
        "stage5_resumed": bool(stage5.get("resumed")),
    }
    timing_path.write_text(json.dumps(timing, indent=2) + "\n")

    stage4_manifest = stage_manifest_path(target, "stage4")
    stage5_manifest = stage_manifest_path(target, stage5_stage)
    if not stage4_manifest.is_file() or not stage5_manifest.is_file():
        worldgen_outputs.commit()
        raise RuntimeError("Stage45 completed without Stage 4/5 manifests")
    manifest = build_stage_manifest(
        job_id=job_id,
        stage=stage45_stage,
        hyworld_revision=HYWORLD2_REVISION,
        input_fingerprint=fingerprint_files(
            [stage4_manifest, stage5_manifest],
            root=target,
        ),
        config={
            "profile": "stage4+stage5-single-worker-v1",
            "gpu": GPU,
            "steps": steps,
            "export_mesh": bool(export_mesh),
        },
    )
    write_stage_manifest(target, stage45_stage, manifest)
    worldgen_outputs.commit()

    return {
        **timing,
        "stage4": stage4,
        "stage5": stage5,
    }


@app.function(
    image=hyworld2_worldgen_stage5_image,
    gpu=GPU,
    cpu=16.0,
    memory=65536,
    volumes={
        "/models": model_cache.with_mount_options(read_only=True),
        "/runtime-cache": runtime_cache,
        "/worldgen": worldgen_outputs,
    },
    secrets=[hf_secret],
    timeout=60 * 60,
)
def worldgen_case000_stage45_smoke(job_id: str = "case000") -> dict:
    """Run Stage 4 + the non-destructive 100-step Stage 5 smoke in one RTX worker."""
    import json
    import time

    worldgen_outputs.reload()
    target = resolve_worldgen_job_root(job_id)
    assert_stage5_static_cache()

    total_started = time.perf_counter()
    stage4_started = time.perf_counter()
    stage4 = run_stage4_core(
        job_id=job_id,
        # The smoke Stage5 commit below persists the Stage4 dataset as well.
        commit_worldgen=None,
        commit_failure_worldgen=worldgen_outputs.commit,
    )
    stage4_wall_s = time.perf_counter() - stage4_started

    stage5_started = time.perf_counter()
    stage5 = run_stage5_smoke_core(
        job_id=job_id,
        commit_worldgen=worldgen_outputs.commit,
        commit_runtime_cache=runtime_cache.commit,
    )
    stage5_wall_s = time.perf_counter() - stage5_started
    timing = {
        "steps": 100,
        "stage4_s": round(stage4_wall_s, 3),
        "stage5_smoke_s": round(stage5_wall_s, 3),
        "stage45_smoke_s": round(time.perf_counter() - total_started, 3),
        "stage4_resumed": bool(stage4.get("resumed")),
        "gpu_peak_used_mib": stage5.get("gpu_peak_used_mib"),
    }
    (target / "stage45_smoke_timing.json").write_text(json.dumps(timing, indent=2) + "\n")
    worldgen_outputs.commit()
    return {**timing, "stage4": stage4, "stage5_smoke": stage5}
