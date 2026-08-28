from __future__ import annotations

import io
from pathlib import Path

from .contracts import model_spec


def load_pipeline(model_id: str, model_root: Path):
    import torch
    from diffusers import SanaSprintPipeline

    model_spec(model_id)
    path = model_root / model_id
    marker = path / ".complete"
    if not marker.is_file():
        raise FileNotFoundError(f"model snapshot is not ready: {model_id}")
    pipe = SanaSprintPipeline.from_pretrained(
        str(path),
        torch_dtype=torch.bfloat16,
        local_files_only=True,
    )
    pipe.to("cuda")
    return pipe


def generate_png(pipe, request: dict[str, object]) -> bytes:
    import torch

    generator = torch.Generator(device="cuda").manual_seed(int(request["seed"]))
    result = pipe(
        prompt=str(request["prompt"]),
        width=int(request["width"]),
        height=int(request["height"]),
        num_inference_steps=int(request["steps"]),
        guidance_scale=float(request["guidance"]),
        generator=generator,
    )
    image = result.images[0]
    validate_image_size(image, request)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def model_snapshot_ready(path: Path) -> bool:
    return (path / ".complete").is_file() and (path / "model_index.json").is_file()


def validate_image_size(image, request: dict[str, object]) -> None:
    expected = (int(request["width"]), int(request["height"]))
    if getattr(image, "size", None) != expected:
        raise RuntimeError(f"unexpected image size: {getattr(image, 'size', None)} != {expected}")
