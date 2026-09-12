from __future__ import annotations

from pathlib import Path

STAGE_CACHE_ENV = "PIXAL3D_SUPPRESS_STAGE_EMPTY_CACHE"
EXPECTED_STAGE_CACHE_CALLS = 5
STAGE_PROFILE_MARKER = "# modal-provider: PIXAL3D_STAGE_PROFILE_V1"
PIPELINE_STAGE_NAMES = (
    "sparse_structure",
    "shape_lr",
    "shape_upsample",
    "shape_hr",
    "texture",
    "decode",
)


def _pipeline_path(source_dir: str) -> Path:
    return Path(source_dir) / "pixal3d/pipelines/pixal3d_image_to_3d.py"


def patch_pixal3d_stage_profiling(source_dir: str) -> dict[str, object]:
    """Instrument the pinned Pixal3D monolithic pipeline without changing math.

    The upstream ``run()`` method otherwise exposes the entire 3D cascade as one
    opaque wall-time bucket.  This patch records the six native stages on the
    pipeline instance so the worker can persist them into benchmark evidence.
    CUDA is synchronized only at existing stage boundaries; no sampler, tensor,
    model placement, quality setting or output path is changed.
    """

    path = _pipeline_path(source_dir)
    source = path.read_text(encoding="utf-8")
    if STAGE_PROFILE_MARKER in source:
        missing = [name for name in PIPELINE_STAGE_NAMES if f'"{name}_s"' not in source]
        if missing:
            raise RuntimeError(f"partial Pixal3D stage-profile patch detected: {missing}")
        return {"path": str(path), "patched": False, "stages": list(PIPELINE_STAGE_NAMES)}

    if "import time\n" not in source:
        import_anchor = "from typing import *\n"
        if source.count(import_anchor) != 1:
            raise RuntimeError("Pixal3D profiling import anchor changed upstream")
        source = source.replace(import_anchor, import_anchor + "import time\n", 1)

    init_anchor = "        torch.manual_seed(seed)\n"
    if source.count(init_anchor) != 1:
        raise RuntimeError("Pixal3D profiling seed anchor changed upstream")
    init = (
        init_anchor
        + f"        {STAGE_PROFILE_MARKER}\n"
        + "        self.last_stage_timings = {}\n"
        + "        self.last_stage_metrics = {}\n"
        + "        _pixal_stage_t0 = time.perf_counter()\n"
    )
    source = source.replace(init_anchor, init, 1)

    transitions = (
        (
            "        # ---- Stage 2: Shape LR 512 (proj) ----\n",
            "sparse_structure",
            '        self.last_stage_metrics["sparse_structure_tokens"] = int(coords.shape[0])\n',
        ),
        (
            "        # ---- Stage 3a: Upsample LR → HR ----\n",
            "shape_lr",
            '        self.last_stage_metrics["shape_lr_tokens"] = int(lr_slat.coords.shape[0])\n',
        ),
        (
            "        # ---- Stage 3b: Shape HR (proj) ----\n",
            "shape_upsample",
            '        self.last_stage_metrics["shape_hr_candidate_tokens"] = int(hr_coords_unique.shape[0])\n'
            '        self.last_stage_metrics["actual_hr_resolution"] = int(actual_hr_resolution)\n',
        ),
        (
            "        # ---- Stage 4: Texture (proj) ----\n",
            "shape_hr",
            '        self.last_stage_metrics["shape_hr_tokens"] = int(shape_slat.coords.shape[0])\n',
        ),
        (
            "        # ---- Stage 5: Decode ----\n",
            "texture",
            '        self.last_stage_metrics["texture_tokens"] = int(tex_slat.coords.shape[0])\n',
        ),
    )
    for anchor, stage_name, metrics in transitions:
        if source.count(anchor) != 1:
            raise RuntimeError(f"Pixal3D profiling stage anchor changed upstream: {stage_name}")
        record = (
            "        torch.cuda.synchronize()\n"
            f'        self.last_stage_timings["{stage_name}_s"] = time.perf_counter() - _pixal_stage_t0\n'
            + metrics
            + "        _pixal_stage_t0 = time.perf_counter()\n\n"
            + anchor
        )
        source = source.replace(anchor, record, 1)

    decode_anchor = "        out_mesh = self.decode_latent(shape_slat, tex_slat, res)\n"
    if source.count(decode_anchor) != 1:
        raise RuntimeError("Pixal3D profiling decode anchor changed upstream")
    decode_record = (
        decode_anchor
        + "        torch.cuda.synchronize()\n"
        + '        self.last_stage_timings["decode_s"] = time.perf_counter() - _pixal_stage_t0\n'
        + '        self.last_stage_metrics["resolution"] = int(res)\n'
    )
    source = source.replace(decode_anchor, decode_record, 1)

    if any(f'"{name}_s"' not in source for name in PIPELINE_STAGE_NAMES):
        raise RuntimeError("Pixal3D profiling patch verification failed")
    path.write_text(source, encoding="utf-8")
    return {"path": str(path), "patched": True, "stages": list(PIPELINE_STAGE_NAMES)}


def patch_pixal3d_stage_cache_guard(source_dir: str) -> dict[str, object]:
    """Make Pixal3D's stage-boundary ``empty_cache`` calls benchmark-switchable.

    Production behavior is unchanged by default. Setting
    ``PIXAL3D_SUPPRESS_STAGE_EMPTY_CACHE=1`` in a *separate Modal container*
    suppresses only the five unconditional cache releases inside the pinned
    Pixal3D image-to-3D pipeline. This exists solely for a controlled allocator
    A/B test; it does not change model quality, sampler settings, or GLB export.

    The patch is deliberately strict and idempotent so an upstream source drift
    fails the image build instead of silently changing the benchmark contract.
    """
    path = _pipeline_path(source_dir)
    source = path.read_text(encoding="utf-8")

    marker = f'os.environ.get("{STAGE_CACHE_ENV}", "0")'
    marker_count = source.count(marker)
    if marker_count == EXPECTED_STAGE_CACHE_CALLS:
        return {
            "path": str(path),
            "patched": False,
            "guarded_calls": marker_count,
            "env": STAGE_CACHE_ENV,
        }
    if marker_count:
        raise RuntimeError(
            f"partial Pixal3D stage-cache patch detected: {marker_count}/"
            f"{EXPECTED_STAGE_CACHE_CALLS} guards"
        )

    original = "        torch.cuda.empty_cache()"
    original_count = source.count(original)
    if original_count != EXPECTED_STAGE_CACHE_CALLS:
        raise RuntimeError(
            "Pixal3D stage-cache source drift: expected "
            f"{EXPECTED_STAGE_CACHE_CALLS} unconditional calls, got {original_count}"
        )

    if "import os\n" not in source:
        import_anchor = "from typing import *\n"
        if source.count(import_anchor) != 1:
            raise RuntimeError("Pixal3D import anchor changed upstream")
        source = source.replace(import_anchor, import_anchor + "import os\n", 1)

    guarded = (
        f'        if os.environ.get("{STAGE_CACHE_ENV}", "0") != "1":\n'
        "            torch.cuda.empty_cache()"
    )
    source = source.replace(original, guarded)
    if source.count(marker) != EXPECTED_STAGE_CACHE_CALLS:
        raise RuntimeError("Pixal3D stage-cache patch verification failed")

    path.write_text(source, encoding="utf-8")
    return {
        "path": str(path),
        "patched": True,
        "guarded_calls": EXPECTED_STAGE_CACHE_CALLS,
        "env": STAGE_CACHE_ENV,
    }
