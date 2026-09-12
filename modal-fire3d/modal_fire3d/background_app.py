"""Background-only controlled reruns; original reconstruction is never overwritten."""

from __future__ import annotations

import modal

from .app import (
    VOLUMES,
    _ensure_flash_attn,
    _ensure_pytorch3d,
    build_artifacts,
    data,
    models,
    outputs,
)
from .runtime import (
    FIRE3D_GPU,
    FIRE3D_RUNTIME_CACHE_MOUNT,
    FIRE3D_RUNTIME_CACHE_VOLUME,
    FIRE3D_SOURCE,
    fire3d_image,
    prepare_runtime_cache,
)

app = modal.App("modal-fire3d-background")
runtime_cache = modal.Volume.from_name(FIRE3D_RUNTIME_CACHE_VOLUME, create_if_missing=True)
PERFORMANCE_VOLUMES = {**VOLUMES, FIRE3D_RUNTIME_CACHE_MOUNT: runtime_cache}
SNAPSHOT_SOURCE_RUN = "20260911T204708Z"


def _snapshot_preload_command() -> list[str]:
    """Build the accepted 512 command used only to derive model-cache keys."""
    import sys
    from pathlib import Path

    from .performance import build_background_command

    source = Path("/outputs/acceptance") / SNAPSHOT_SOURCE_RUN
    return build_background_command(
        source / "logs/reconstruction_batch.log",
        python=sys.executable,
        runner=Path(__file__).with_name("background_runner.py"),
        source_manifest=source / "manifests/batch_scenes.json",
        output_root=Path("/tmp/fire3d-snapshot-preload"),
        policy="no_room_filter",
        decode_resolution=512,
        detailed_profile=False,
        model_cache=True,
    )


def _run_background_job(
    source_run: str,
    run_id: str,
    policy: str,
    *,
    decode_resolution: int,
    detailed_profile: bool,
    persistent: bool,
    call_index: int | None = None,
) -> dict:
    import contextlib
    import json
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    import torch

    from .performance import build_background_command, validate_run_id

    validate_run_id(source_run)
    validate_run_id(run_id)
    source = Path("/outputs/acceptance") / source_run
    target = Path("/outputs/background") / run_id
    target.mkdir(parents=True, exist_ok=False)
    source_manifest = source / "manifests/batch_scenes.json"
    entries = json.loads(source_manifest.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("background optimization requires exactly one source scene")
    scene_id = str(entries[0]["scene_id"])
    runner = Path(__file__).with_name("background_runner.py")
    command = build_background_command(
        source / "logs/reconstruction_batch.log",
        python=sys.executable,
        runner=runner,
        source_manifest=source_manifest,
        output_root=target / "reconstruction",
        policy=policy,
        decode_resolution=decode_resolution,
        detailed_profile=detailed_profile,
        model_cache=persistent,
    )
    previous_env = os.environ.get("FF_SINGLE_IMAGE_ROOT")
    previous_cwd = os.getcwd()
    os.environ["FF_SINGLE_IMAGE_ROOT"] = f"{FIRE3D_SOURCE}/data/single_image"
    log_path = target / "run.log"
    cache_before = None
    cache_after = None
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    try:
        if persistent:
            from .background_runner import cache_info, run

            os.chdir(FIRE3D_SOURCE)
            cache_before = cache_info()
            with (
                log_path.open("w", encoding="utf-8") as log,
                contextlib.redirect_stdout(log),
                contextlib.redirect_stderr(log),
            ):
                returncode = run(command[2:])
            cache_after = cache_info()
        else:
            with log_path.open("w", encoding="utf-8") as log:
                result = subprocess.run(
                    command,
                    cwd=FIRE3D_SOURCE,
                    env=dict(os.environ),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            returncode = result.returncode
    finally:
        os.chdir(previous_cwd)
        if previous_env is None:
            os.environ.pop("FF_SINGLE_IMAGE_ROOT", None)
        else:
            os.environ["FF_SINGLE_IMAGE_ROOT"] = previous_env
    torch.cuda.synchronize()
    elapsed_s = time.perf_counter() - started
    inference_summary_path = target / "reconstruction" / scene_id / "inference_summary.json"
    inference_summary = (
        json.loads(inference_summary_path.read_text(encoding="utf-8"))
        if inference_summary_path.is_file()
        else None
    )
    appearance = (inference_summary or {}).get("appearance") or {}
    receipt = {
        "command": command,
        "returncode": returncode,
        "elapsed_s": elapsed_s,
        "policy": policy,
        "source_run": source_run,
        "run_id": run_id,
        "scene_id": scene_id,
        "persistent": persistent,
        "call_index": call_index,
        "decode_resolution": decode_resolution,
        "detailed_profile": detailed_profile,
        "cache_before": cache_before,
        "cache_after": cache_after,
        "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
        "phase_timing_seconds": (
            inference_summary.get("phase_timing_seconds") if inference_summary else None
        ),
        "appearance_timing_seconds": appearance.get("phase_timing_seconds"),
        "pipeline_wall_seconds": (
            inference_summary.get("pipeline_wall_seconds") if inference_summary else None
        ),
    }
    (target / "execution.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    if persistent:
        runtime_cache.commit()
    outputs.commit()
    if returncode:
        raise RuntimeError(log_path.read_text(encoding="utf-8")[-10000:])
    receipt["files"] = [
        {"path": str(path.relative_to(target)), "bytes": path.stat().st_size}
        for path in target.rglob("*")
        if path.is_file()
    ]
    return receipt


@app.function(
    image=fire3d_image,
    gpu=FIRE3D_GPU,
    cpu=32,
    memory=65536,
    volumes=VOLUMES,
    timeout=3600,
)
def reconstruct_background(source_run: str, run_id: str, policy: str = "no_room_filter"):
    """Compatibility baseline: one fresh process, official 512 decode, no model cache."""
    for volume in (models, data, outputs, build_artifacts):
        volume.reload()
    _ensure_flash_attn(verify_cuda=True)
    _ensure_pytorch3d(verify_cuda=True)
    return _run_background_job(
        source_run,
        run_id,
        policy,
        decode_resolution=512,
        detailed_profile=False,
        persistent=False,
    )


@app.cls(
    image=fire3d_image,
    gpu=FIRE3D_GPU,
    cpu=32.0,
    memory=65536,
    volumes=PERFORMANCE_VOLUMES,
    timeout=3600,
    startup_timeout=20 * 60,
    min_containers=0,
    max_containers=1,
    scaledown_window=30,
    single_use_containers=True,
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
class BackgroundWorker:
    """Keep Fire3D reconstruction models resident across background experiments."""

    @modal.enter(snap=True)
    def load_snapshot(self) -> None:
        """Load checkpoints once into the GPU snapshot; do not run scene inference."""
        import json
        import os
        import time

        for volume in (models, data, outputs, build_artifacts, runtime_cache):
            volume.reload()
        self.runtime_cache_paths = prepare_runtime_cache()
        self.flash_attn = _ensure_flash_attn(verify_cuda=True)
        self.pytorch3d = _ensure_pytorch3d(verify_cuda=True)
        command = _snapshot_preload_command()
        previous_cwd = os.getcwd()
        started = time.perf_counter()
        try:
            os.chdir(FIRE3D_SOURCE)
            from .background_runner import preload_model_cache

            self.snapshot_profile = preload_model_cache(command[2:])
        finally:
            os.chdir(previous_cwd)
        self.snapshot_profile["elapsed_s"] = time.perf_counter() - started
        runtime_cache.commit()
        print("FIRE3D_SNAPSHOT_BUILD " + json.dumps(self.snapshot_profile), flush=True)

    @modal.enter()
    def load_after_restore(self) -> None:
        """Refresh mutable volumes and validate the restored model cache."""
        import json
        import time

        import torch

        from .background_runner import cache_info

        outputs.reload()
        # Do not reload the compiler/autotune cache Volume here. Triton and
        # FlexGEMM retain open cache handles inside the memory snapshot, and a
        # Modal Volume reload is correctly rejected while those files are open.
        torch.cuda.synchronize()
        restored_cache = cache_info()
        if restored_cache.get("entries") != 4:
            raise RuntimeError(f"Fire3D snapshot restored incomplete model cache: {restored_cache}")
        self.started_at = time.time()
        self.calls = 0
        self.restore_profile = {
            "cache": restored_cache,
            "gpu": torch.cuda.get_device_name(0),
            "allocated_gb": round(torch.cuda.memory_allocated() / 1024**3, 3),
        }
        print("FIRE3D_SNAPSHOT_RESTORE " + json.dumps(self.restore_profile), flush=True)

    @modal.method()
    def reconstruct(
        self,
        source_run: str,
        run_id: str,
        policy: str = "no_room_filter",
        decode_resolution: int = 512,
        detailed_profile: bool = False,
    ) -> dict:
        outputs.reload()
        self.calls += 1
        result = _run_background_job(
            source_run,
            run_id,
            policy,
            decode_resolution=decode_resolution,
            detailed_profile=detailed_profile,
            persistent=True,
            call_index=self.calls,
        )
        result["worker"] = {
            "started_at": self.started_at,
            "call_index": self.calls,
            "flash_attn": self.flash_attn,
            "pytorch3d": self.pytorch3d,
            "runtime_cache_paths": self.runtime_cache_paths,
            "snapshot_profile": self.snapshot_profile,
            "restore_profile": self.restore_profile,
        }
        return result
