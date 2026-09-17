"""Pi3 inference adapter for arbitrary FIRE3D single-image inputs."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

from .preprocess import Pi3Prediction, PreparedDataset, materialize_prepared_dataset

PI3_SOURCE = "/opt/Pi3"
PI3_SOURCE_REVISION = "9fa3ddb3f8d53041f8b2738df404f62223bbaa7b"
PI3_MODEL_ID = "yyfz233/Pi3"
PI3_MODEL_REVISION = "b1a2678bfcdc34b4d3b4b199ea959629782106ff"
# Published Hugging Face model.safetensors digest, recorded for provenance. The
# Hub loader owns cache/download validation; this value makes the expected weight
# artifact explicit in every generated preprocess manifest.
PI3_MODEL_SHA256 = "33580e4702ac671558aedeab1148fd08118f7ce45bdbeb99f3e3cf340062875d"
PI3_PIXEL_LIMIT = 255_000
PI3_CONFIDENCE_THRESHOLD = 0.1
PI3_EDGE_RTOL = 0.03

_MODEL_CACHE: dict[tuple[str, str], Any] = {}


def release_pi3_models() -> None:
    """Release Pi3 weights before the much larger FIRE3D subprocess starts."""

    import gc

    models = list(_MODEL_CACHE.values())
    _MODEL_CACHE.clear()
    for model in models:
        del model
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _pi3_target_size(width: int, height: int, pixel_limit: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    if pixel_limit < 14 * 14:
        raise ValueError("pixel_limit is too small for Pi3")
    scale = math.sqrt(pixel_limit / (width * height))
    target_w = width * scale
    target_h = height * scale
    k = max(1, round(target_w / 14))
    m = max(1, round(target_h / 14))
    while (k * 14) * (m * 14) > pixel_limit:
        if k / m > target_w / target_h:
            k = max(1, k - 1)
        else:
            m = max(1, m - 1)
    return k * 14, m * 14


def _load_image_tensor(image_path: Path, *, pixel_limit: int, device: str):
    """Match Pi3's published resize policy without importing its utility module."""

    import numpy as np
    import torch
    from PIL import Image, ImageOps

    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        target_w, target_h = _pi3_target_size(image.width, image.height, pixel_limit)
        image = image.resize((target_w, target_h), Image.Resampling.LANCZOS)
        array = np.asarray(image, dtype=np.float32) / 255.0
    tensor = torch.from_numpy(array).permute(2, 0, 1).contiguous().to(device)
    return tensor, (target_h, target_w)


def _load_pi3_model(*, pi3_root: Path, device: str):
    import torch

    resolved = str(pi3_root.resolve())
    if resolved not in sys.path:
        sys.path.insert(0, resolved)
    try:
        from pi3.models.pi3 import Pi3
    except ImportError as exc:
        raise RuntimeError(
            f"Pi3 source is unavailable at {pi3_root}; deploy the FIRE3D runtime with Pi3 support"
        ) from exc

    cache_key = (resolved, device)
    model = _MODEL_CACHE.get(cache_key)
    if model is None:
        torch.set_float32_matmul_precision("high")
        model = Pi3.from_pretrained(PI3_MODEL_ID, revision=PI3_MODEL_REVISION).to(device).eval()
        _MODEL_CACHE[cache_key] = model
    return model


def infer_pi3(
    image_path: Path,
    *,
    pi3_root: Path = Path(PI3_SOURCE),
    device: str = "cuda",
    pixel_limit: int = PI3_PIXEL_LIMIT,
    confidence_threshold: float = PI3_CONFIDENCE_THRESHOLD,
    edge_rtol: float = PI3_EDGE_RTOL,
) -> Pi3Prediction:
    """Run the paper's Pi3 model and retain its dense camera-local point map."""

    import numpy as np
    import torch

    image_path = Path(image_path).expanduser().resolve()
    pi3_root = Path(pi3_root).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("Pi3 raw-image preprocessing requires a CUDA GPU")
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be in [0,1]")
    if edge_rtol <= 0:
        raise ValueError("edge_rtol must be positive")

    tensor, model_size = _load_image_tensor(image_path, pixel_limit=pixel_limit, device=device)
    model = _load_pi3_model(pi3_root=pi3_root, device=device)
    autocast_enabled = device.startswith("cuda")
    if autocast_enabled:
        capability = torch.cuda.get_device_capability(torch.device(device))
        dtype = torch.bfloat16 if capability[0] >= 8 else torch.float16
    else:
        dtype = torch.float32

    with torch.no_grad(), torch.amp.autocast(
        device_type="cuda", dtype=dtype, enabled=autocast_enabled
    ):
        result = model(tensor[None, None])

    local_points_t = result["local_points"][0, 0].float()
    confidence_t = torch.sigmoid(result["conf"][0, 0, ..., 0].float())
    valid_t = (
        torch.isfinite(local_points_t).all(dim=-1)
        & (local_points_t[..., 2] > 0)
        & torch.isfinite(confidence_t)
        & (confidence_t >= confidence_threshold)
    )
    try:
        from pi3.utils.geometry import depth_normal_edge
    except ImportError as exc:
        raise RuntimeError("Pi3 geometry utilities are unavailable") from exc
    edge_t = depth_normal_edge(local_points_t, rtol=edge_rtol, mask=valid_t)

    local_points = local_points_t.cpu().numpy().astype(np.float32, copy=False)
    confidence = confidence_t.cpu().numpy().astype(np.float32, copy=False)
    edge_mask = edge_t.cpu().numpy().astype(bool, copy=False)
    camera_pose = result.get("camera_poses")
    camera_pose_np = None
    if camera_pose is not None:
        camera_pose_np = camera_pose[0, 0].float().cpu().numpy().astype(np.float64, copy=False)

    if tuple(local_points.shape[:2]) != tuple(model_size):
        raise RuntimeError(
            f"Pi3 returned {local_points.shape[:2]} but input raster was {model_size}"
        )
    return Pi3Prediction(
        local_points=local_points,
        confidence=confidence,
        edge_mask=edge_mask,
        model_input_size=model_size,
        model_id=PI3_MODEL_ID,
        model_revision=(
            f"source:{PI3_SOURCE_REVISION};hub:{PI3_MODEL_REVISION};"
            f"model.safetensors:sha256:{PI3_MODEL_SHA256}"
        ),
        camera_pose=camera_pose_np,
    )


def prepare_raw_image(
    image_path: Path,
    *,
    data_root: Path,
    scene_id: str | None = None,
    pi3_root: Path = Path(PI3_SOURCE),
    device: str = "cuda",
    pixel_limit: int = PI3_PIXEL_LIMIT,
    confidence_threshold: float = PI3_CONFIDENCE_THRESHOLD,
    edge_rtol: float = PI3_EDGE_RTOL,
    jpeg_quality: int = 95,
) -> PreparedDataset:
    """Run Pi3 then materialize FIRE3D's native ``single_image`` dataset."""

    prediction = infer_pi3(
        image_path,
        pi3_root=pi3_root,
        device=device,
        pixel_limit=pixel_limit,
        confidence_threshold=confidence_threshold,
        edge_rtol=edge_rtol,
    )
    return materialize_prepared_dataset(
        image_path,
        prediction,
        data_root=data_root,
        scene_id=scene_id,
        confidence_threshold=confidence_threshold,
        jpeg_quality=jpeg_quality,
    )
