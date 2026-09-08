from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .hyworld2_runtime import HYWORLD2_REVISION, HYWORLD2_SOURCE
from .worldgen_job import (
    build_stage_manifest,
    fingerprint_files,
    manifest_matches,
    resolve_worldgen_job_root,
    stage5_artifacts,
    stage5_result_dir,
    stage_manifest_path,
    stage_profile_file,
    stage_profile_name,
    write_stage_manifest,
)

CommitCallback = Callable[[], None] | None


def _commit(callback: CommitCallback) -> None:
    if callback is not None:
        callback()


def assert_stage5_static_cache() -> Path:
    """Fail before Stage 4 when the persisted LPIPS VGG cache is unavailable."""
    path = Path("/models/torch/hub/checkpoints/vgg16-397923af.pth")
    if not path.is_file():
        raise RuntimeError(
            "Stage 5 VGG16 cache missing; run preflight_worldgen_case000_stage5 first"
        )
    return path


def run_stage4_core(
    job_id: str = "case000",
    force: bool = False,
    *,
    commit_worldgen: CommitCallback = None,
    commit_failure_worldgen: CommitCallback = None,
    defer_stale_cleanup: bool = False,
) -> dict:
    """Prepare the official HYWorld2 GS dataset inside the current GPU worker."""
    import json
    import os
    import shutil
    import subprocess
    import sys
    import threading
    import time
    from pathlib import Path

    os.environ["HF_HOME"] = "/models/huggingface"
    os.environ["HUGGINGFACE_HUB_CACHE"] = "/models/huggingface/hub"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["CUDA_CACHE_PATH"] = "/runtime-cache/cuda-cache"
    os.environ["CUDA_CACHE_MAXSIZE"] = str(4 * 1024**3)
    os.environ["TORCH_EXTENSIONS_DIR"] = "/runtime-cache/torch-extensions"
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = "/runtime-cache/torchinductor"
    os.environ["TRITON_CACHE_DIR"] = "/runtime-cache/triton"

    target = resolve_worldgen_job_root(job_id)
    generation_bank = target / "render_results/generation_bank_worldstereo-memory-dmd"
    required_stage3 = [generation_bank / "global_pcd.ply", generation_bank / "aligned_pcd.ply"]
    missing_stage3 = [
        str(path.relative_to(target)) for path in required_stage3 if not path.is_file()
    ]
    if missing_stage3:
        raise RuntimeError(f"Stage 3 incomplete: missing {missing_stage3}")

    stage4_inputs = [*required_stage3]
    for path in (
        generation_bank / "pcd_info.json",
        generation_bank / "sky_pcd.ply",
        target / "meta_info.json",
        target / "panorama.png",
        target / "render_results/full_depth_prediction.pt",
        target / "render_results/sky_mask.png",
    ):
        if path.is_file():
            stage4_inputs.append(path)
    stage4_inputs.extend(
        sorted(target.glob("render_results/*/traj*/worldstereo-memory-dmd_result.mp4"))
    )
    stage4_inputs.extend(sorted(generation_bank.glob("*/*/depths/*.png")))
    stage4_manifest = build_stage_manifest(
        job_id=job_id,
        stage="stage4",
        hyworld_revision=HYWORLD2_REVISION,
        input_fingerprint=fingerprint_files(stage4_inputs, root=target),
        config={"save_normal": True, "split_sky": True, "split_align": False},
    )

    gs_data = target / "gs_data"
    cameras_path = gs_data / "cameras.json"
    points_path = gs_data / "points.ply"
    sky_points_path = gs_data / "sky_points.ply"
    meta_info_path = gs_data / "meta_info.json"
    if not force and cameras_path.is_file() and points_path.is_file() and meta_info_path.is_file():
        payload = json.loads(cameras_path.read_text())
        camera_count = len([key for key in payload if key not in {"width", "height"}])
        images = sorted((gs_data / "images").glob("*.png"))
        depths = sorted((gs_data / "depths").glob("*.png"))
        normals = sorted((gs_data / "normals").glob("*.png"))
        if camera_count and len(images) == camera_count and len(normals) == camera_count:
            manifest_ok = manifest_matches(target, "stage4", stage4_manifest)
            legacy_adopted = (
                job_id == "case000" and not stage_manifest_path(target, "stage4").exists()
            )
            if manifest_ok or legacy_adopted:
                if legacy_adopted:
                    write_stage_manifest(target, "stage4", stage4_manifest)
                    _commit(commit_worldgen)
                return {
                    "resumed": True,
                    "manifest_adopted": legacy_adopted,
                    "stage4_s": 0.0,
                    "camera_count": camera_count,
                    "image_count": len(images),
                    "depth_count": len(depths),
                    "normal_count": len(normals),
                    "points_bytes": points_path.stat().st_size,
                    "sky_points_bytes": (
                        sky_points_path.stat().st_size if sky_points_path.is_file() else 0
                    ),
                }

    worldgen_root = Path(HYWORLD2_SOURCE) / "hyworld2/worldgen"
    log_path = target / "stage4.log"
    timing_path = target / "stage4_timing.json"
    build_data = (
        target / ".modal-world" / f"stage4-build-{os.getpid()}-{time.time_ns()}"
    )
    build_data.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-X",
        "faulthandler",
        "-u",
        "gen_gs_data.py",
        "--root_path",
        str(target),
        "--custom_out_name",
        str(build_data),
        "--save_normal",
        "--split_sky",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{worldgen_root}:{HYWORLD2_SOURCE}"
    env["PYTHONFAULTHANDLER"] = "1"
    env["RANK"] = "0"
    env["LOCAL_RANK"] = "0"
    env["WORLD_SIZE"] = "1"

    stop_monitor = threading.Event()
    gpu_peak_mib = None

    def monitor_gpu() -> None:
        nonlocal gpu_peak_mib
        while not stop_monitor.wait(1.0):
            try:
                raw = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    timeout=5,
                ).splitlines()[0]
                sample_mib = int(raw.strip())
                gpu_peak_mib = max(gpu_peak_mib or 0, sample_mib)
            except (subprocess.SubprocessError, ValueError, IndexError):
                pass

    monitor = None
    if os.environ.get("MODAL_WORLD_DEBUG_GPU_SAMPLER") == "1":
        monitor = threading.Thread(target=monitor_gpu, daemon=True)
        monitor.start()
    started = time.perf_counter()
    try:
        with log_path.open("w") as log:
            completed = subprocess.run(
                command,
                cwd=worldgen_root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=50 * 60,
            )
    finally:
        if monitor is not None:
            stop_monitor.set()
            monitor.join(timeout=5)

    stage4_s = time.perf_counter() - started
    build_cameras_path = build_data / "cameras.json"
    build_points_path = build_data / "points.ply"
    build_sky_points_path = build_data / "sky_points.ply"
    build_meta_info_path = build_data / "meta_info.json"
    camera_count = 0
    if build_cameras_path.is_file():
        payload = json.loads(build_cameras_path.read_text())
        camera_count = len([key for key in payload if key not in {"width", "height"}])
    images = sorted((build_data / "images").glob("*.png"))
    depths = sorted((build_data / "depths").glob("*.png"))
    normals = sorted((build_data / "normals").glob("*.png"))
    timing = {
        "stage4_s": round(stage4_s, 3),
        "gpu_peak_used_mib": gpu_peak_mib,
        "gpu_sampler_enabled": monitor is not None,
        "returncode": completed.returncode,
        "camera_count": camera_count,
        "image_count": len(images),
        "depth_count": len(depths),
        "normal_count": len(normals),
        "points_exists": build_points_path.is_file(),
        "sky_points_exists": build_sky_points_path.is_file(),
    }
    timing_path.write_text(json.dumps(timing, indent=2) + "\n")

    if completed.returncode != 0:
        shutil.rmtree(build_data, ignore_errors=True)
        _commit(commit_failure_worldgen or commit_worldgen)
        tail = log_path.read_text(errors="replace")[-30000:]
        raise RuntimeError(f"WorldGen Stage 4 failed with exit {completed.returncode}:\n{tail}")
    if (
        not build_cameras_path.is_file()
        or not build_points_path.is_file()
        or not build_meta_info_path.is_file()
    ):
        shutil.rmtree(build_data, ignore_errors=True)
        _commit(commit_failure_worldgen or commit_worldgen)
        raise RuntimeError("Stage 4 completed without required GS dataset files")
    if not camera_count or len(images) != camera_count or len(normals) != camera_count:
        shutil.rmtree(build_data, ignore_errors=True)
        _commit(commit_failure_worldgen or commit_worldgen)
        raise RuntimeError(
            f"Stage 4 dataset count mismatch: cameras={camera_count} images={len(images)} "
            f"normals={len(normals)} depths={len(depths)}"
        )

    # Preserve a validated prior dataset until the replacement is complete. The
    # renames are same-Volume metadata operations; recursive stale-tree cleanup
    # may be deferred and overlapped with Stage 5 in the merged worker.
    promotion_started = time.perf_counter()
    stale_data = None
    if gs_data.exists():
        stale_data = (
            target / ".modal-world" / f"stage4-stale-{os.getpid()}-{time.time_ns()}"
        )
        gs_data.rename(stale_data)
    try:
        build_data.rename(gs_data)
    except Exception:
        if stale_data is not None and stale_data.exists() and not gs_data.exists():
            stale_data.rename(gs_data)
        raise
    promotion_s = time.perf_counter() - promotion_started

    write_stage_manifest(target, "stage4", stage4_manifest)
    if stale_data is not None and not defer_stale_cleanup:
        shutil.rmtree(stale_data, ignore_errors=True)
    _commit(commit_worldgen)
    return {
        **timing,
        "promotion_s": round(promotion_s, 3),
        "points_bytes": points_path.stat().st_size,
        "sky_points_bytes": (sky_points_path.stat().st_size if sky_points_path.is_file() else 0),
        "stale_data_dir": str(stale_data) if stale_data is not None else None,
        "stage4_log_tail": log_path.read_text(errors="replace")[-8000:],
    }



def run_stage5_core(
    job_id: str = "case000",
    force: bool = False,
    steps: int = 8000,
    export_mesh: bool = True,
    *,
    commit_worldgen: CommitCallback = None,
    commit_failure_worldgen: CommitCallback = None,
    commit_runtime_cache: CommitCallback = None,
) -> dict:
    """Run the documented single-GPU 3DGS profile inside the current GPU worker."""
    import json
    import os
    import shutil
    import subprocess
    import sys
    import threading
    import time
    from pathlib import Path

    os.environ["TORCH_HOME"] = "/models/torch"
    os.environ["XDG_CACHE_HOME"] = "/models/cache"
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    os.environ["PYTHONFAULTHANDLER"] = "1"
    os.environ["CUDA_CACHE_PATH"] = "/runtime-cache/cuda-cache"
    os.environ["CUDA_CACHE_MAXSIZE"] = str(4 * 1024**3)
    os.environ["TORCH_EXTENSIONS_DIR"] = "/runtime-cache/torch-extensions"
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = "/runtime-cache/torchinductor"
    os.environ["TRITON_CACHE_DIR"] = "/runtime-cache/triton"

    target = resolve_worldgen_job_root(job_id)
    data_dir = target / "gs_data"
    steps = int(steps)
    if steps <= 0:
        raise ValueError("steps must be > 0")
    result_dir = stage5_result_dir(target, steps)
    stage5_stage = stage_profile_name("stage5", steps)
    required = [
        data_dir / "cameras.json",
        data_dir / "points.ply",
        data_dir / "meta_info.json",
        data_dir / "images",
        data_dir / "normals",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Stage 5 full missing GS data: {missing}")
    vgg_cache = Path("/models/torch/hub/checkpoints/vgg16-397923af.pth")
    if not vgg_cache.is_file():
        raise RuntimeError(
            "Stage 5 VGG16 cache missing; run preflight_worldgen_case000_stage5 first"
        )

    stage4_manifest = stage_manifest_path(target, "stage4")
    fingerprint_inputs = [
        data_dir / "cameras.json",
        data_dir / "points.ply",
        data_dir / "meta_info.json",
    ]
    for optional in (data_dir / "sky_points.ply", data_dir / "align_points.ply"):
        if optional.is_file():
            fingerprint_inputs.append(optional)
    for directory in (data_dir / "images", data_dir / "depths", data_dir / "normals"):
        fingerprint_inputs.extend(sorted(directory.glob("*.png")))
    if stage4_manifest.is_file():
        fingerprint_inputs.append(stage4_manifest)
    manifest = build_stage_manifest(
        job_id=job_id,
        stage=stage5_stage,
        hyworld_revision=HYWORLD2_REVISION,
        input_fingerprint=fingerprint_files(fingerprint_inputs, root=target),
        config={
            "profile": "single-gpu-full-v1",
            "steps": steps,
            "save_ply": True,
            "convert_to_spz": True,
            "export_mesh": bool(export_mesh),
            "mesh_voxel_size": 0.05,
        },
    )
    artifacts = stage5_artifacts(target, steps)
    final_ply = artifacts.ply
    final_spz = artifacts.spz
    final_mesh = artifacts.mesh
    final_outputs = (final_ply, final_spz, final_mesh) if export_mesh else (final_ply, final_spz)
    log_path = stage_profile_file(target, "stage5", steps, ".log")
    timing_path = stage_profile_file(target, "stage5", steps, "_timing.json")
    outputs_complete = all(path.is_file() and path.stat().st_size > 0 for path in final_outputs)
    if not force and outputs_complete:
        if manifest_matches(target, stage5_stage, manifest):
            return {
                "resumed": True,
                "adopted": False,
                "steps": steps,
                "result_dir": str(result_dir),
                "ply_bytes": final_ply.stat().st_size,
                "spz_bytes": final_spz.stat().st_size,
                "mesh_bytes": final_mesh.stat().st_size if export_mesh else 0,
            }

        # HYWorld2's pinned single-GPU trainer used to call an unguarded
        # dist.barrier() *after* PLY/SPZ and mesh export. Adopt that exact
        # terminal-failure shape only when the inputs have not changed.
        prior_timing = None
        if timing_path.is_file():
            try:
                prior_timing = json.loads(timing_path.read_text())
            except (json.JSONDecodeError, OSError):
                prior_timing = None
        outputs_fresh = min(path.stat().st_mtime_ns for path in final_outputs) >= max(
            path.stat().st_mtime_ns for path in fingerprint_inputs
        )
        terminal_barrier_failure = (
            export_mesh
            and prior_timing is not None
            and prior_timing.get("steps") == steps
            and prior_timing.get("returncode") == 1
            and outputs_fresh
            and log_path.is_file()
            and "UnboundLocalError: cannot access local variable 'dist'"
            in log_path.read_text(errors="replace")
        )
        if terminal_barrier_failure:
            prior_timing["adopted_terminal_barrier_failure"] = True
            timing_path.write_text(json.dumps(prior_timing, indent=2) + "\n")
            write_stage_manifest(target, stage5_stage, manifest)
            _commit(commit_worldgen)
            return {
                "resumed": True,
                "adopted": True,
                "upstream_returncode": 1,
                "steps": steps,
                "result_dir": str(result_dir),
                "ply_bytes": final_ply.stat().st_size,
                "spz_bytes": final_spz.stat().st_size,
                "mesh_bytes": final_mesh.stat().st_size if export_mesh else 0,
            }
    if result_dir.exists():
        shutil.rmtree(result_dir)

    worldgen_root = Path(HYWORLD2_SOURCE) / "hyworld2/worldgen"
    command = [
        sys.executable,
        "-X",
        "faulthandler",
        "-u",
        "-m",
        "world_gs_trainer",
        "default",
        "--data_dir",
        str(data_dir),
        "--result_dir",
        str(result_dir),
        "--max_steps",
        str(steps),
        "--save_steps",
        str(steps),
        "--eval_steps",
        str(steps),
        "--ply_steps",
        str(steps),
        "--save_ply",
        "--convert_to_spz",
        "--disable_video",
        "--disable_viewer",
        "--use_scale_regularization",
        "--antialiased",
        "--depth_loss",
        "--normal_loss",
        "--sky_depth_from_pcd",
        "--use_mask_gaussian",
        "--mask_export_stochastic",
        "--no-mask-export-anchor-protection",
        "--use_anchor_protection",
        "--strategy.refine-start-iter",
        "800",
        "--strategy.refine-stop-iter",
        "4000",
        "--strategy.refine-every",
        "533",
        "--strategy.refine-scale2d-stop-iter",
        "4000",
        "--strategy.reset-every",
        "99990",
        "--strategy.grow-grad2d",
        "0.0001",
        "--strategy.prune-scale3d",
        "0.1",
    ]
    if export_mesh:
        command.append("--export_mesh")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{worldgen_root}:{HYWORLD2_SOURCE}"

    stop_monitor = threading.Event()
    gpu_peak_mib = 0

    def monitor_gpu() -> None:
        nonlocal gpu_peak_mib
        while not stop_monitor.wait(1.0):
            try:
                raw = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    text=True,
                    timeout=5,
                ).splitlines()[0]
                gpu_peak_mib = max(gpu_peak_mib, int(raw.strip()))
            except (subprocess.SubprocessError, ValueError, IndexError):
                pass

    monitor = None
    if os.environ.get("MODAL_WORLD_DEBUG_GPU_SAMPLER") == "1":
        monitor = threading.Thread(target=monitor_gpu, daemon=True)
        monitor.start()
    started = time.perf_counter()
    try:
        with log_path.open("w") as log:
            completed = subprocess.run(
                command,
                cwd=worldgen_root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=170 * 60,
            )
    finally:
        if monitor is not None:
            stop_monitor.set()
            monitor.join(timeout=5)

    elapsed = time.perf_counter() - started
    timing = {
        "steps": steps,
        "stage5_s": round(elapsed, 3),
        "gpu_peak_used_mib": gpu_peak_mib if monitor is not None else None,
        "gpu_sampler_enabled": monitor is not None,
        "returncode": completed.returncode,
    }
    timing_path.write_text(json.dumps(timing, indent=2) + "\n")
    _commit(commit_runtime_cache)
    if completed.returncode != 0:
        _commit(commit_failure_worldgen or commit_worldgen)
        raise RuntimeError(
            f"Stage 5 full failed with exit {completed.returncode}:\n"
            f"{log_path.read_text(errors='replace')[-40000:]}"
        )
    missing_outputs = [
        str(path) for path in final_outputs if not path.is_file()
    ]
    if missing_outputs:
        _commit(commit_failure_worldgen or commit_worldgen)
        raise RuntimeError(f"Stage 5 full completed without final outputs: {missing_outputs}")

    write_stage_manifest(target, stage5_stage, manifest)
    _commit(commit_worldgen)
    return {
        **timing,
        "resumed": False,
        "result_dir": str(result_dir),
        "ply_bytes": final_ply.stat().st_size,
        "spz_bytes": final_spz.stat().st_size,
        "mesh_bytes": final_mesh.stat().st_size if export_mesh else 0,
        "mesh": str(final_mesh) if export_mesh else None,
        "log_tail": log_path.read_text(errors="replace")[-10000:],
    }


def run_stage5_smoke_core(
    job_id: str = "case000",
    *,
    commit_worldgen: CommitCallback = None,
    commit_runtime_cache: CommitCallback = None,
) -> dict:
    """Run the non-destructive 100-step 3DGS smoke profile in the current worker."""
    import json
    import os
    import shutil
    import subprocess
    import sys
    import threading
    import time
    from pathlib import Path

    os.environ["TORCH_HOME"] = "/models/torch"
    os.environ["XDG_CACHE_HOME"] = "/models/cache"
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    os.environ["PYTHONFAULTHANDLER"] = "1"
    os.environ["CUDA_CACHE_PATH"] = "/runtime-cache/cuda-cache"
    os.environ["CUDA_CACHE_MAXSIZE"] = str(4 * 1024**3)
    os.environ["TORCH_EXTENSIONS_DIR"] = "/runtime-cache/torch-extensions"
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = "/runtime-cache/torchinductor"
    os.environ["TRITON_CACHE_DIR"] = "/runtime-cache/triton"

    target = resolve_worldgen_job_root(job_id)
    data_dir = target / "gs_data"
    result_dir = target / "gs_smoke_result"
    if result_dir.exists():
        shutil.rmtree(result_dir)
    required = [
        data_dir / "cameras.json",
        data_dir / "points.ply",
        data_dir / "images",
        data_dir / "normals",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Stage 5 smoke missing GS data: {missing}")
    vgg_cache = Path("/models/torch/hub/checkpoints/vgg16-397923af.pth")
    if not vgg_cache.is_file():
        raise RuntimeError(
            "Stage 5 VGG16 cache missing; run preflight_worldgen_case000_stage5 first"
        )

    worldgen_root = Path(HYWORLD2_SOURCE) / "hyworld2/worldgen"
    log_path = target / "stage5_smoke.log"
    timing_path = target / "stage5_smoke_timing.json"
    steps = 100
    command = [
        sys.executable,
        "-X",
        "faulthandler",
        "-u",
        "-m",
        "world_gs_trainer",
        "default",
        "--data_dir",
        str(data_dir),
        "--result_dir",
        str(result_dir),
        "--max_steps",
        str(steps),
        "--save_steps",
        str(steps),
        "--ply_steps",
        str(steps),
        "--save_ply",
        "--convert_to_spz",
        "--disable_video",
        "--disable_viewer",
        "--use_scale_regularization",
        "--antialiased",
        "--depth_loss",
        "--normal_loss",
        "--sky_depth_from_pcd",
        "--use_mask_gaussian",
        "--mask_export_stochastic",
        "--no-mask-export-anchor-protection",
        "--use_anchor_protection",
        "--strategy.refine-start-iter",
        "10",
        "--strategy.refine-stop-iter",
        "50",
        "--strategy.refine-every",
        "7",
        "--strategy.refine-scale2d-stop-iter",
        "50",
        "--strategy.reset-every",
        "99990",
        "--strategy.grow-grad2d",
        "0.0001",
        "--strategy.prune-scale3d",
        "0.1",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{worldgen_root}:{HYWORLD2_SOURCE}"

    stop_monitor = threading.Event()
    gpu_peak_mib = 0

    def monitor_gpu() -> None:
        nonlocal gpu_peak_mib
        while not stop_monitor.wait(1.0):
            try:
                raw = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    text=True,
                    timeout=5,
                ).splitlines()[0]
                gpu_peak_mib = max(gpu_peak_mib, int(raw.strip()))
            except (subprocess.SubprocessError, ValueError, IndexError):
                pass

    monitor = threading.Thread(target=monitor_gpu, daemon=True)
    monitor.start()
    started = time.perf_counter()
    try:
        with log_path.open("w") as log:
            completed = subprocess.run(
                command,
                cwd=worldgen_root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=15 * 60,
            )
    finally:
        stop_monitor.set()
        monitor.join(timeout=5)

    elapsed = time.perf_counter() - started
    checkpoints = sorted(result_dir.rglob("*.pt"))
    plys = sorted(result_dir.rglob("*.ply"))
    spzs = sorted(result_dir.rglob("*.spz"))
    timing = {
        "steps": steps,
        "stage5_smoke_s": round(elapsed, 3),
        "gpu_peak_used_mib": gpu_peak_mib,
        "returncode": completed.returncode,
        "checkpoint_count": len(checkpoints),
        "ply_count": len(plys),
        "spz_count": len(spzs),
    }
    timing_path.write_text(json.dumps(timing, indent=2) + "\n")
    _commit(commit_runtime_cache)
    _commit(commit_worldgen)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Stage 5 smoke failed with exit {completed.returncode}:\n"
            f"{log_path.read_text(errors='replace')[-30000:]}"
        )
    if not checkpoints or not plys or not spzs:
        raise RuntimeError(f"Stage 5 smoke completed without checkpoint/PLY: {timing}")
    return {
        **timing,
        "checkpoint_bytes": sum(path.stat().st_size for path in checkpoints),
        "ply_bytes": sum(path.stat().st_size for path in plys),
        "spz_bytes": sum(path.stat().st_size for path in spzs),
        "log_tail": log_path.read_text(errors="replace")[-8000:],
    }
