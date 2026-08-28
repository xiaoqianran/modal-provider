from __future__ import annotations

import hashlib
import io

CANONICAL_SIZE = 1024
_ALPHA_THRESHOLD = 8
_MASK_FOREGROUND_THRESHOLD = 0.5
_MASK_CLOSE_ITERATIONS = 2


class BackgroundMaskRequired(ValueError):
    """Raised when an opaque source needs a foreground mask before conditioning."""


def _dependencies():
    import numpy as np
    from PIL import Image, ImageOps
    from scipy import ndimage

    return np, Image, ImageOps, ndimage


def _load_source(data: bytes):
    _, Image, ImageOps, _ = _dependencies()
    if not data:
        raise ValueError("source image is empty")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            source = ImageOps.exif_transpose(opened)
            source_format = opened.format
    except Exception as exc:
        raise ValueError("source image could not be decoded") from exc
    if source_format not in {"PNG", "JPEG", "WEBP"}:
        raise ValueError(f"unsupported source image format: {source_format}")
    return source, source_format


def _meaningful_alpha(source):
    if "A" not in source.getbands():
        return None
    alpha = source.convert("RGBA").getchannel("A")
    extrema = alpha.getextrema()
    if extrema is None:
        return None
    alpha_min, alpha_max = extrema
    if alpha_max <= _ALPHA_THRESHOLD or alpha_min == 255:
        return None
    return alpha


def refine_mask(mask):
    np, Image, _, ndimage = _dependencies()
    alpha = np.asarray(mask.convert("L"), dtype=np.float32) / 255.0
    solid = alpha >= _MASK_FOREGROUND_THRESHOLD
    if not np.any(solid):
        return mask.convert("L")
    filled = ndimage.binary_fill_holes(solid)
    closed = ndimage.binary_closing(
        filled,
        structure=np.ones((3, 3), dtype=bool),
        iterations=_MASK_CLOSE_ITERATIONS,
    )
    region = ndimage.binary_fill_holes(closed | filled)
    repaired = np.where(region, alpha, 0.0)
    added = region & (alpha < _MASK_FOREGROUND_THRESHOLD)
    repaired = np.where(added, 1.0, repaired)
    return Image.fromarray((repaired * 255).astype(np.uint8), mode="L")


def _foreground_bbox(mask):
    binary = mask.point(lambda value: 255 if value > _ALPHA_THRESHOLD else 0)
    bbox = binary.getbbox()
    if bbox is None:
        raise ValueError("conditioning found no visible foreground")
    return bbox


def _letterbox_rgba(rgba, bbox, size: int = CANONICAL_SIZE):
    _, Image, _, _ = _dependencies()
    crop = rgba.crop(bbox)
    width, height = crop.size
    if width <= 0 or height <= 0:
        raise ValueError("foreground bounding box is invalid")
    # Preserve at least a one-pixel transparent border on every axis.  This
    # keeps the old max-fit behavior while guaranteeing the canonical alpha
    # invariant even for square foreground bounding boxes.
    available = max(1, size - 2)
    scale = min(available / width, available / height)
    target = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized = crop.resize(target, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = ((size - target[0]) // 2, (size - target[1]) // 2)
    canvas.alpha_composite(resized, offset)
    return canvas


def _png_bytes(image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", compress_level=6)
    return output.getvalue()


def condition_image(data: bytes, predicted_mask: bytes | None = None) -> dict[str, object]:
    """Convert a public source image into the internal canonical RGBA contract.

    Existing meaningful alpha is trusted and preserved. Opaque sources require
    a foreground mask. The caller may provide it, or the client may obtain one
    directly from the T4 RemBgWorker before local refinement and letterboxing.
    """
    source, source_format = _load_source(data)
    rgba = source.convert("RGBA")
    alpha = _meaningful_alpha(source)
    strategy = "preserve-alpha"

    if alpha is None:
        if predicted_mask is None:
            raise BackgroundMaskRequired("opaque source requires background removal")
        _, Image, _, _ = _dependencies()
        try:
            with Image.open(io.BytesIO(predicted_mask)) as opened:
                opened.load()
                mask = opened.convert("L")
        except Exception as exc:
            raise ValueError("predicted background mask is invalid") from exc
        if mask.size != rgba.size:
            mask = mask.resize(rgba.size, Image.Resampling.LANCZOS)
        alpha = refine_mask(mask)
        strategy = "birefnet"

    rgba.putalpha(alpha)
    bbox = _foreground_bbox(alpha)
    canonical = _letterbox_rgba(rgba, bbox)
    canonical_bytes = _png_bytes(canonical)
    histogram = alpha.histogram()
    foreground_pixels = sum(histogram[_ALPHA_THRESHOLD + 1 :])
    total_pixels = rgba.width * rgba.height
    return {
        "canonical_bytes": canonical_bytes,
        "canonical_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_format": source_format.lower(),
        "source_size": [rgba.width, rgba.height],
        "foreground_bbox": list(bbox),
        "foreground_ratio": foreground_pixels / total_pixels if total_pixels else 0.0,
        "canonical_size": [CANONICAL_SIZE, CANONICAL_SIZE],
        "strategy": strategy,
    }
