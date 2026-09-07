from __future__ import annotations

from pathlib import Path


STAGE_CACHE_ENV = "PIXAL3D_SUPPRESS_STAGE_EMPTY_CACHE"
EXPECTED_STAGE_CACHE_CALLS = 5


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
    path = Path(source_dir) / "pixal3d/pipelines/pixal3d_image_to_3d.py"
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
