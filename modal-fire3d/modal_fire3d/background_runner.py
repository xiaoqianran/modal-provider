"""Invoke unchanged upstream reconstruction with extra condition-point diagnostics.

``run`` intentionally executes the upstream runner in-process. Its module-level
``_MODEL_CACHE`` therefore survives across calls in a persistent Modal class,
while the official subprocess entrypoint remains available for baseline runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _upstream_runner():
    import sys

    if "/opt/Fire3D" not in sys.path:
        sys.path.insert(0, "/opt/Fire3D")
    from benchmarks.scene_reconstruction import run_lc64_geometry as runner

    return runner


def cache_info() -> dict[str, int]:
    runner = _upstream_runner()
    return {"entries": len(runner._MODEL_CACHE)}


def _parse_args(argv: Sequence[str]):
    """Parse one upstream runner command without leaking process argv state."""
    import sys
    from pathlib import Path

    runner = _upstream_runner()
    original_argv = sys.argv
    sys.argv = [str(Path(runner.__file__)), *list(argv)]
    try:
        return runner.parse_args()
    finally:
        sys.argv = original_argv


def preload_model_cache(argv: Sequence[str]) -> dict[str, Any]:
    """Load the four model groups used by a cached Fire3D reconstruction.

    This deliberately performs no scene inference. It mirrors the cache keys
    used by the pinned upstream runner so a Modal GPU memory snapshot can
    restore directly into the normal request path with all checkpoints already
    resident.
    """
    import time

    import torch

    runner = _upstream_runner()
    args = _parse_args(argv)
    if not args.model_cache:
        raise ValueError("snapshot preload requires --model-cache")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    device = torch.device(args.device)
    timings: dict[str, float] = {}

    started = time.perf_counter()
    flow_key = (
        "flow_models",
        str(args.ss_run_dir),
        str(args.ss_checkpoint),
        args.ss_model_family,
        args.ss_use_ema,
        str(args.shape_run_dir),
        str(args.shape_checkpoint),
        args.shape_model_family,
        args.shape_use_ema,
        args.max_cond_len,
        args.dino_upsample,
        args.anyup_frame_batch_size,
        str(device),
    )
    ss_model, _shape_model, _flow_metadata = runner._cached_load(
        True, flow_key, lambda: runner.load_flow_models(args, device)
    )
    timings["flow_models"] = time.perf_counter() - started

    started = time.perf_counter()
    decoder_key = (
        "decoders",
        str(args.ss_vae_root),
        args.ss_vae_checkpoint,
        args.ss_vae_use_ema,
        str(args.shape_vae_root),
        args.shape_vae_checkpoint,
        args.shape_vae_use_ema,
        args.shape_decoder_pretrained,
        str(device),
    )
    runner._cached_load(True, decoder_key, lambda: runner.load_decoders(args, device))
    timings["geometry_decoders"] = time.perf_counter() - started

    started = time.perf_counter()
    pbr_max_cond_len = runner.resolve_pbr_max_cond_len(args)
    pbr_key = (
        "pbr_flow",
        str(args.pbr_run_dir),
        str(args.pbr_checkpoint),
        args.pbr_model_family,
        args.pbr_use_ema,
        pbr_max_cond_len,
        args.dino_upsample,
        args.anyup_frame_batch_size,
        str(device),
    )
    runner._cached_load(
        True,
        pbr_key,
        lambda: runner.load_pbr_flow_model(
            run_dir=args.pbr_run_dir,
            checkpoint=args.pbr_checkpoint,
            device=device,
            max_cond_len=pbr_max_cond_len,
            dino_upsample=args.dino_upsample,
            anyup_frame_batch_size=args.anyup_frame_batch_size,
            use_ema=args.pbr_use_ema,
            model_family=args.pbr_model_family,
            shared_dino_config=dict(ss_model.config),
        ),
    )
    timings["pbr_flow"] = time.perf_counter() - started

    started = time.perf_counter()
    decoder_paths = runner.DecoderPaths(
        shape_x2_root=args.shape_vae_root,
        pbr_x2_root=args.pbr_vae_root,
        shape_x2_checkpoint=args.shape_vae_checkpoint,
        pbr_x2_checkpoint=args.pbr_vae_checkpoint,
        shape_x2_use_ema=args.shape_vae_use_ema,
        pbr_x2_use_ema=args.pbr_vae_use_ema,
        shape_decoder=args.shape_decoder_pretrained,
        pbr_decoder=str(args.pbr_decoder_pretrained),
    )
    bundle_key = ("decoder_bundle", str(decoder_paths), str(device))
    runner._cached_load(
        True,
        bundle_key,
        lambda: runner.load_decoder_bundle(decoder_paths, device),
    )
    timings["appearance_decoders"] = time.perf_counter() - started
    torch.cuda.synchronize()
    return {
        "cache": cache_info(),
        "timings_s": timings,
        "gpu": torch.cuda.get_device_name(0),
        "allocated_gb": round(torch.cuda.memory_allocated() / 1024**3, 3),
    }


def run(argv: Sequence[str] | None = None) -> int:
    import sys
    from pathlib import Path

    import numpy as np

    runner = _upstream_runner()
    original_conditioning = runner.apply_perception_conditioning
    original_argv = sys.argv

    def audited_conditioning(args, data):
        result = original_conditioning(args, data)
        local_id = runner.background_local_instance_id(result)
        mask = result["instance_ids"] == local_id
        destination = Path(args.output_root)
        destination.mkdir(parents=True, exist_ok=True)
        np.savez(
            destination / "background_condition.npz",
            points=result["points"][mask],
            canonical=runner.canonical_points_for_object(result, local_id),
            all_points=result["all_points"],
            instance_ids=result["instance_ids"],
            norm_transform=result["norm_transform"],
        )
        return result

    runner.apply_perception_conditioning = audited_conditioning
    sys.argv = [str(Path(runner.__file__)), *(list(argv) if argv is not None else original_argv[1:])]
    try:
        runner.main()
    except SystemExit as exc:
        code = exc.code
        if code in (None, 0):
            return 0
        return int(code) if isinstance(code, int) else 1
    finally:
        runner.apply_perception_conditioning = original_conditioning
        sys.argv = original_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
