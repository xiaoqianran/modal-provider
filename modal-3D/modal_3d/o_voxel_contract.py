from __future__ import annotations

from collections.abc import Mapping

REQUIRED_PBR_CHANNELS = ("base_color", "metallic", "roughness", "alpha")


def _nonempty_size(value, name: str) -> int:
    if value is None:
        raise ValueError(f"O-Voxel intermediate is missing {name}")
    numel = getattr(value, "numel", None)
    if callable(numel):
        size = int(numel())
    else:
        try:
            size = len(value)
        except TypeError as exc:
            raise ValueError(f"O-Voxel intermediate {name} is not sized") from exc
    if size <= 0:
        raise ValueError(f"O-Voxel intermediate {name} is empty")
    return size


def _leading_count(value, name: str) -> int | None:
    shape = getattr(value, "shape", None)
    if shape is None or len(shape) == 0:
        return None
    count = int(shape[0])
    if count <= 0:
        raise ValueError(f"O-Voxel intermediate {name} has an empty leading dimension")
    return count


def validate_o_voxel_pbr_intermediate(
    *,
    vertices,
    faces,
    attrs,
    coords,
    attr_layout: Mapping[str, object],
    grid_size: int | None = None,
    voxel_size: float | None = None,
) -> dict:
    """Fail closed before PBR remesh/bake if O-Voxel semantic data is incomplete.

    This function only inspects the intermediate; it never mutates tensors or
    changes post-processing parameters. Both Pixal3D and TRELLIS.2 are expected
    to carry base-color, metallic, roughness and alpha all the way into GLB
    extraction.
    """
    _nonempty_size(vertices, "vertices")
    _nonempty_size(faces, "faces")
    _nonempty_size(attrs, "attrs")
    _nonempty_size(coords, "coords")
    attrs_count = _leading_count(attrs, "attrs")
    coords_count = _leading_count(coords, "coords")
    if attrs_count is not None and coords_count is not None and attrs_count != coords_count:
        raise ValueError(
            f"O-Voxel intermediate attrs/coords count mismatch: {attrs_count} != {coords_count}"
        )

    if not isinstance(attr_layout, Mapping):
        raise TypeError("O-Voxel intermediate attr_layout must be a mapping")
    missing = [channel for channel in REQUIRED_PBR_CHANNELS if channel not in attr_layout]
    if missing:
        raise ValueError(f"O-Voxel intermediate is missing PBR channels: {', '.join(missing)}")

    required_attr_width = 0
    for channel in REQUIRED_PBR_CHANNELS:
        selector = attr_layout[channel]
        if not isinstance(selector, slice):
            raise TypeError(f"O-Voxel PBR channel {channel} must use a slice layout")
        if selector.start is None or selector.stop is None or selector.stop <= selector.start:
            raise ValueError(f"O-Voxel PBR channel {channel} has an invalid slice")
        required_attr_width = max(required_attr_width, int(selector.stop))

    attrs_shape = getattr(attrs, "shape", None)
    if attrs_shape is not None and len(attrs_shape) >= 2 and int(attrs_shape[-1]) < required_attr_width:
        raise ValueError(
            f"O-Voxel intermediate attrs width {int(attrs_shape[-1])} < required {required_attr_width}"
        )

    if grid_size is None and voxel_size is None:
        raise ValueError("O-Voxel intermediate requires grid_size or voxel_size")
    if grid_size is not None and (not isinstance(grid_size, int) or isinstance(grid_size, bool) or grid_size <= 0):
        raise ValueError("O-Voxel grid_size must be a positive integer")
    if voxel_size is not None and float(voxel_size) <= 0:
        raise ValueError("O-Voxel voxel_size must be positive")

    return {
        "vertices": _leading_count(vertices, "vertices"),
        "faces": _leading_count(faces, "faces"),
        "coords": _leading_count(coords, "coords"),
        "pbr_channels": list(REQUIRED_PBR_CHANNELS),
        "grid_size": grid_size,
        "voxel_size": None if voxel_size is None else float(voxel_size),
    }
