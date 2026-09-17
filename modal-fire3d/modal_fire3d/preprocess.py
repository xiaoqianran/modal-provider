"""Raw-image to FIRE3D single-image dataset conversion.

The model-specific Pi3 inference stays in :mod:`modal_fire3d.pi3_preprocessor`.
This module is deliberately CPU-only so the dataset contract can be tested
without importing torch or constructing a Modal image.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

SUPPORTED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
CAMERA_SCHEMA = "fire3d_single_image_camera_v1"
PREPROCESS_SCHEMA = "modal_fire3d_preprocess_v1"


@dataclass(frozen=True)
class Pi3Prediction:
    """Dense single-view Pi3 output before FIRE3D regridding."""

    local_points: np.ndarray
    confidence: np.ndarray
    edge_mask: np.ndarray
    model_input_size: tuple[int, int]
    model_id: str
    model_revision: str
    camera_pose: np.ndarray | None = None


@dataclass(frozen=True)
class PreparedDataset:
    """Materialized FIRE3D dataset root and scene metadata."""

    data_root: Path
    dataset_root: Path
    scene_dir: Path
    scene_id: str
    manifest_path: Path
    valid_ratio: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_raw_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES


def derive_scene_id(path: Path) -> str:
    """Return a stable ASCII/alphanumeric scene id accepted by FIRE3D."""

    return f"raw{sha256_file(path)[:16]}"


def _load_normalized_rgb(path: Path) -> tuple[Image.Image, dict[str, object]]:
    if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        raise ValueError(f"unsupported raw image type: {path.suffix or '<none>'}")
    try:
        with Image.open(path) as source:
            source_format = source.format or path.suffix.lstrip(".").upper()
            transposed = ImageOps.exif_transpose(source)
            had_alpha = "A" in transposed.getbands() or "transparency" in transposed.info
            if had_alpha:
                rgba = transposed.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                background.alpha_composite(rgba)
                rgb = background.convert("RGB")
            else:
                rgb = transposed.convert("RGB")
            rgb.load()
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot decode JPG/PNG input: {path}") from exc
    width, height = rgb.size
    if width < 32 or height < 32:
        raise ValueError(f"raw image is too small for FIRE3D: {width}x{height}")
    return rgb, {
        "source_format": source_format,
        "alpha_composited_on_white": had_alpha,
        "width": width,
        "height": height,
    }


def _prediction_arrays(prediction: Pi3Prediction) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    points = np.asarray(prediction.local_points, dtype=np.float64)
    confidence = np.asarray(prediction.confidence, dtype=np.float64)
    edges = np.asarray(prediction.edge_mask, dtype=bool)
    if points.ndim != 3 or points.shape[-1] != 3:
        raise ValueError(f"Pi3 local_points must have shape (H,W,3), got {points.shape}")
    if confidence.shape == (*points.shape[:2], 1):
        confidence = confidence[..., 0]
    if confidence.shape != points.shape[:2]:
        raise ValueError(
            f"Pi3 confidence shape {confidence.shape} does not match points {points.shape[:2]}"
        )
    if edges.shape != points.shape[:2]:
        raise ValueError(f"Pi3 edge mask shape {edges.shape} does not match points {points.shape[:2]}")
    if tuple(prediction.model_input_size) != tuple(points.shape[:2]):
        raise ValueError(
            "Pi3 model_input_size must equal the dense point-map spatial size: "
            f"{prediction.model_input_size} != {points.shape[:2]}"
        )
    return points, confidence, edges


def recover_pinhole_intrinsics(
    local_points: np.ndarray,
    valid_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Fit fx, fy, cx, cy from a dense Pi3 camera-local point map.

    Pi3 local points follow ``x/z`` and ``y/z`` image rays.  Fitting the pinhole
    equation lets us safely change raster resolution by resampling *depth* and
    back-projecting, instead of interpolating XYZ across depth discontinuities.
    """

    points = np.asarray(local_points, dtype=np.float64)
    if points.ndim != 3 or points.shape[-1] != 3:
        raise ValueError("local_points must have shape (H,W,3)")
    height, width = points.shape[:2]
    valid = np.isfinite(points).all(axis=-1) & (points[..., 2] > 1e-8)
    if valid_mask is not None:
        valid &= np.asarray(valid_mask, dtype=bool)
    if int(valid.sum()) < 32:
        raise ValueError("too few valid Pi3 points to recover camera intrinsics")

    yy, xx = np.indices((height, width), dtype=np.float64)
    x_over_z = points[..., 0] / points[..., 2]
    y_over_z = points[..., 1] / points[..., 2]

    def fit(coord: np.ndarray, ratio: np.ndarray, axis: str) -> tuple[float, float]:
        design = np.column_stack([ratio[valid], np.ones(int(valid.sum()), dtype=np.float64)])
        values = coord[valid]
        solution, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
        focal, principal = (float(solution[0]), float(solution[1]))
        residual = np.median(np.abs(design @ solution - values))
        if not np.isfinite(focal) or abs(focal) < 1e-6 or not np.isfinite(principal):
            raise ValueError(f"Pi3 {axis} intrinsics fit is degenerate")
        if residual > max(height, width) * 0.1:
            raise ValueError(
                f"Pi3 {axis} intrinsics fit residual is too large: {residual:.3f}px"
            )
        return focal, principal

    fx, cx = fit(xx, x_over_z, "x")
    fy, cy = fit(yy, y_over_z, "y")
    return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)


def scale_intrinsics(
    intrinsics: np.ndarray,
    *,
    source_size: tuple[int, int],
    target_size: tuple[int, int],
) -> np.ndarray:
    """Scale pixel-center intrinsics across a pure image resize."""

    source_h, source_w = source_size
    target_h, target_w = target_size
    if min(source_h, source_w, target_h, target_w) <= 0:
        raise ValueError("image sizes must be positive")
    sx = target_w / source_w
    sy = target_h / source_h
    k = np.asarray(intrinsics, dtype=np.float64).copy()
    k[0, 0] *= sx
    k[1, 1] *= sy
    k[0, 2] = (k[0, 2] + 0.5) * sx - 0.5
    k[1, 2] = (k[1, 2] + 0.5) * sy - 0.5
    return k


def _nearest_model_indices(
    *,
    target_size: tuple[int, int],
    model_size: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    target_h, target_w = target_size
    model_h, model_w = model_size
    # Raster-center mapping for a resize covering the same field of view.
    model_y = (np.arange(target_h, dtype=np.float64) + 0.5) * model_h / target_h - 0.5
    model_x = (np.arange(target_w, dtype=np.float64) + 0.5) * model_w / target_w - 0.5
    yi = np.clip(np.rint(model_y).astype(np.int64), 0, model_h - 1)
    xi = np.clip(np.rint(model_x).astype(np.int64), 0, model_w - 1)
    return yi, xi


def build_fire3d_point_grid(
    prediction: Pi3Prediction,
    *,
    native_size: tuple[int, int],
    confidence_threshold: float = 0.1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert dense Pi3 output to FIRE3D's ordered H//2 by W//2 grid.

    Depth is selected with nearest-neighbour sampling to avoid blending across
    geometry discontinuities.  XYZ is then back-projected at the target pixel
    centers using recovered intrinsics. Invalid/low-confidence/edge samples stay
    in the lattice as NaN rows; FIRE3D's reconstruction loader already has a
    defined nearest-valid fill policy for those rows.
    """

    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be in [0,1]")
    points, confidence, edges = _prediction_arrays(prediction)
    native_h, native_w = native_size
    target_h, target_w = native_h // 2, native_w // 2
    if target_h < 16 or target_w < 16:
        raise ValueError("raw image is too small after FIRE3D half-resolution conversion")

    model_valid = (
        np.isfinite(points).all(axis=-1)
        & (points[..., 2] > 1e-8)
        & np.isfinite(confidence)
        & (confidence >= confidence_threshold)
        & ~edges
    )
    k_model = recover_pinhole_intrinsics(points, np.isfinite(points).all(axis=-1))
    k_native = scale_intrinsics(
        k_model,
        source_size=points.shape[:2],
        target_size=native_size,
    )

    yi, xi = _nearest_model_indices(target_size=(target_h, target_w), model_size=points.shape[:2])
    depth = points[..., 2][np.ix_(yi, xi)]
    valid = model_valid[np.ix_(yi, xi)] & np.isfinite(depth) & (depth > 1e-8)

    yy, xx = np.indices((target_h, target_w), dtype=np.float64)
    # Half-resolution cell centers expressed in native-image pixel coordinates.
    u_native = 2.0 * xx + 0.5
    v_native = 2.0 * yy + 0.5
    fx, fy = k_native[0, 0], k_native[1, 1]
    cx, cy = k_native[0, 2], k_native[1, 2]
    grid = np.empty((target_h, target_w, 3), dtype=np.float32)
    grid[..., 0] = ((u_native - cx) / fx * depth).astype(np.float32)
    grid[..., 1] = ((v_native - cy) / fy * depth).astype(np.float32)
    grid[..., 2] = depth.astype(np.float32)
    grid[~valid] = np.nan
    return grid, valid, k_native


def write_binary_xyz_ply(path: Path, points: np.ndarray) -> None:
    """Write an ordered float32 XYZ cloud as binary little-endian PLY."""

    flat = np.asarray(points, dtype=np.float32).reshape(-1, 3).astype("<f4", copy=False)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {flat.shape[0]}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    ).encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(header)
        stream.write(flat.tobytes(order="C"))


def _camera_record(
    k: np.ndarray,
    *,
    width: int,
    height: int,
    source_size: tuple[int, int],
    crop_top: int = 0,
    crop_left: int = 0,
) -> dict[str, object]:
    return {
        "frame": {
            "eye": [0.0, 0.0, 0.0],
            "lookat": [0.0, 0.0, 1.0],
            "up": [0.0, -1.0, 0.0],
        },
        "forward": [0.0, 0.0, 1.0],
        "K": np.asarray(k, dtype=np.float64).tolist(),
        "width": int(width),
        "height": int(height),
        "crop_top": int(crop_top),
        "crop_left": int(crop_left),
        "source_size": [int(source_size[0]), int(source_size[1])],
    }


def build_camera_payload(k_native: np.ndarray, *, native_size: tuple[int, int]) -> dict[str, object]:
    native_h, native_w = native_size
    grid_h, grid_w = native_h // 2, native_w // 2
    crop_h, crop_w = (grid_h // 16) * 16, (grid_w // 16) * 16
    top, left = (grid_h - crop_h) // 2, (grid_w - crop_w) // 2
    k_reconstruction = np.asarray(k_native, dtype=np.float64).copy()
    k_reconstruction[0, 2] -= 2 * left
    k_reconstruction[1, 2] -= 2 * top
    return {
        "schema": CAMERA_SCHEMA,
        "native": _camera_record(
            k_native,
            width=native_w,
            height=native_h,
            source_size=native_size,
        ),
        "reconstruction": _camera_record(
            k_reconstruction,
            width=2 * crop_w,
            height=2 * crop_h,
            source_size=native_size,
            crop_top=2 * top,
            crop_left=2 * left,
        ),
    }


def materialize_prepared_dataset(
    image_path: Path,
    prediction: Pi3Prediction,
    *,
    data_root: Path,
    scene_id: str | None = None,
    confidence_threshold: float = 0.1,
    jpeg_quality: int = 95,
) -> PreparedDataset:
    """Create the exact directory/point-lattice contract consumed by FIRE3D."""

    image_path = Path(image_path).expanduser().resolve()
    data_root = Path(data_root).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    if not 1 <= jpeg_quality <= 100:
        raise ValueError("jpeg_quality must be in [1,100]")
    if scene_id is None:
        scene_id = derive_scene_id(image_path)
    if not scene_id.isascii() or not scene_id.isalnum():
        raise ValueError("scene_id must contain only ASCII letters and digits")

    rgb, source_meta = _load_normalized_rgb(image_path)
    native_w, native_h = rgb.size
    grid, valid, k_native = build_fire3d_point_grid(
        prediction,
        native_size=(native_h, native_w),
        confidence_threshold=confidence_threshold,
    )
    valid_ratio = float(valid.mean())
    if valid_ratio < 0.01:
        raise ValueError(f"Pi3 valid geometry coverage is too low: {valid_ratio:.4f}")

    dataset_root = data_root / "single_image"
    scene_dir = dataset_root / "data" / scene_id
    scene_dir.mkdir(parents=True, exist_ok=True)
    rgb_path = scene_dir / "rgb.jpeg"
    rgb.save(rgb_path, format="JPEG", quality=jpeg_quality, subsampling=0)
    pcd_path = scene_dir / "aligned_pcd.ply"
    write_binary_xyz_ply(pcd_path, grid)

    camera = build_camera_payload(k_native, native_size=(native_h, native_w))
    camera_path = scene_dir / "camera.json"
    camera_path.write_text(json.dumps(camera, indent=2) + "\n", encoding="utf-8")

    source_hash = sha256_file(image_path)
    manifest = {
        "schema": PREPROCESS_SCHEMA,
        "scene_id": scene_id,
        "source": {
            "filename": image_path.name,
            "sha256": source_hash,
            **source_meta,
        },
        "normalized_rgb": {
            "path": "rgb.jpeg",
            "sha256": sha256_file(rgb_path),
            "jpeg_quality": jpeg_quality,
        },
        "geometry": {
            "path": "aligned_pcd.ply",
            "grid_height": native_h // 2,
            "grid_width": native_w // 2,
            "vertex_count": (native_h // 2) * (native_w // 2),
            "ordered_row_major": True,
            "invalid_encoding": "nan_xyz",
            "valid_ratio": valid_ratio,
            "resampling": "nearest_depth_then_pinhole_backprojection",
            "confidence_threshold": confidence_threshold,
            "depth_edge_policy": "pi3_depth_normal_edge_invalidated",
        },
        "camera": {
            "path": "camera.json",
            "schema": CAMERA_SCHEMA,
            "intrinsics_source": "least_squares_from_pi3_local_points",
        },
        "preprocessor": {
            "model": prediction.model_id,
            "model_revision": prediction.model_revision,
            "model_input_height": int(prediction.model_input_size[0]),
            "model_input_width": int(prediction.model_input_size[1]),
        },
        "coordinate_contract": {
            "frame": "pi3_single_image_camera_reference",
            "ground_alignment_verified": False,
            "note": (
                "The FIRE3D paper uses the single-image camera frame as reference for Pi3 input. "
                "No unsupported gravity/ground alignment claim is made by this adapter."
            ),
        },
    }
    if prediction.camera_pose is not None:
        manifest["preprocessor"]["camera_pose"] = np.asarray(
            prediction.camera_pose, dtype=np.float64
        ).tolist()
    manifest_path = scene_dir / "preprocess.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    valid_path = dataset_root / "single_image_valid.txt"
    existing = []
    if valid_path.is_file():
        existing = [line.strip() for line in valid_path.read_text(encoding="utf-8").splitlines()]
    scene_ids = sorted({item for item in existing if item} | {scene_id})
    valid_path.write_text("\n".join(scene_ids) + "\n", encoding="utf-8")

    return PreparedDataset(
        data_root=data_root,
        dataset_root=dataset_root,
        scene_dir=scene_dir,
        scene_id=scene_id,
        manifest_path=manifest_path,
        valid_ratio=valid_ratio,
    )
