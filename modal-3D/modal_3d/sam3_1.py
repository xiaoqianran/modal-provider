from __future__ import annotations

import hashlib
import io
import json
import math
import time
import uuid
from collections import OrderedDict
from pathlib import Path

import modal

APP_NAME = "modal-3d-sam31"
GPU = "L40S"
MAX_IMAGE_PIXELS = 40_000_000
MAX_CONCEPT_CHARS = 160
MAX_CANDIDATES = 24
DEFAULT_MAX_CANDIDATES = 16
DEFAULT_OUTPUT_SIZE = 1024
SCENE_CACHE_SIZE = 1

SAM3_REPO = "facebookresearch/sam3"
SAM3_COMMIT = "8f0b7f4d4e7eda2ed606ebde6702c93359ad01da"
SAM31_REPO = "facebook/sam3.1"
SAM31_REVISION = "daa63191845a41281374e725f4c9e51c7a824460"
SAM31_CHECKPOINT = "sam3.1_multiplex.pt"

SRC = Path("/opt/sam3")
MODEL_DIR = Path("/models/sam31")
CHECKPOINT = MODEL_DIR / SAM31_CHECKPOINT
ARTIFACT_ROOT = Path("/artifacts") / "sam31"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-sam31-weights", create_if_missing=True)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)


download_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("huggingface_hub==0.35.3", "hf_xet==1.6.0", uv_version="0.12.5")
)

cpu_image = modal.Image.debian_slim(python_version="3.12").uv_pip_install(
    "numpy==1.26.4", "Pillow==12.1.0", uv_version="0.12.5"
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.12")
    .apt_install("git")
    .uv_pip_install(
        "torch==2.10.0",
        "torchvision==0.25.0",
        index_url="https://download.pytorch.org/whl/cu128",
        uv_version="0.12.5",
    )
    .uv_pip_install(
        "numpy==1.26.4",
        "Pillow==12.1.0",
        "pycocotools==2.0.10",
        "psutil==7.1.0",
        "timm==1.0.19",
        "tqdm==4.67.1",
        "ftfy==6.1.1",
        "einops==0.8.1",
        "regex==2025.7.34",
        "iopath==0.1.10",
        "typing_extensions==4.15.0",
        "huggingface_hub==0.35.3",
        "hf_xet==1.6.0",
        uv_version="0.12.5",
    )
    .run_commands(
        f"git clone https://github.com/{SAM3_REPO}.git {SRC} && git -C {SRC} checkout {SAM3_COMMIT}",
        f"python -m pip install --no-deps -e {SRC}",
        f"PYTHONPATH={SRC} python -c \"from sam3 import build_sam3_image_model; from sam3.model.sam3_image_processor import Sam3Processor; print('sam3 import ok')\"",
    )
    .env(
        {
            "PYTHONPATH": str(SRC),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        }
    )
)


@app.function(
    image=download_image,
    volumes={"/models": weights},
    cpu=4,
    memory=8192,
    timeout=30 * 60,
    max_containers=1,
    secrets=[modal.Secret.from_name("huggingface")],
)
def sync_weights() -> dict:
    from huggingface_hub import hf_hub_download

    t0 = time.perf_counter()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for filename in (SAM31_CHECKPOINT, "config.json"):
        hf_hub_download(
            SAM31_REPO,
            filename=filename,
            revision=SAM31_REVISION,
            local_dir=MODEL_DIR,
        )
    weights.commit()
    total = sum(p.stat().st_size for p in MODEL_DIR.rglob("*") if p.is_file())
    return {
        "repo": SAM31_REPO,
        "revision": SAM31_REVISION,
        "checkpoint": SAM31_CHECKPOINT,
        "bytes": total,
        "elapsed_s": time.perf_counter() - t0,
    }


def _hex_id(value: str, length: int, name: str) -> str:
    value = str(value)
    if len(value) != length or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"invalid {name}")
    return value


def _validate_concept(concept: str) -> str:
    concept = " ".join(str(concept).split())
    if not concept:
        raise ValueError("concept must not be empty")
    if len(concept) > MAX_CONCEPT_CHARS:
        raise ValueError(f"concept exceeds {MAX_CONCEPT_CHARS} characters")
    return concept


def _validate_max_candidates(value: int) -> int:
    value = int(value)
    if not 1 <= value <= MAX_CANDIDATES:
        raise ValueError(f"max_candidates must be between 1 and {MAX_CANDIDATES}")
    return value


def _validate_output_size(value: int) -> int:
    value = int(value)
    if not 256 <= value <= 2048:
        raise ValueError("output_size must be between 256 and 2048")
    return value


def _scene_path(scene_id: str) -> Path:
    scene_id = _hex_id(scene_id, 64, "scene_id")
    return ARTIFACT_ROOT / "scenes" / scene_id / "input.bin"


def _selection_root(scene_id: str, selection_id: str) -> Path:
    scene_id = _hex_id(scene_id, 64, "scene_id")
    selection_id = _hex_id(selection_id, 32, "selection_id")
    return ARTIFACT_ROOT / "selections" / scene_id / selection_id


def _candidate_id(value: str) -> str:
    value = str(value)
    if len(value) != 3 or value[0] != "c" or not value[1:].isdigit():
        raise ValueError("invalid candidate_id")
    return value


def _box_from_dict(raw: dict) -> tuple[list[float], bool]:
    try:
        cx, cy = float(raw["cx"]), float(raw["cy"])
        width, height = float(raw["width"]), float(raw["height"])
        positive = bool(raw.get("positive", True))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("box must contain numeric cx, cy, width, height") from exc
    values = (cx, cy, width, height)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("box values must be finite")
    if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < width <= 1 and 0 < height <= 1):
        raise ValueError("box coordinates must be normalized to [0, 1]")
    if cx - width / 2 < 0 or cx + width / 2 > 1 or cy - height / 2 < 0 or cy + height / 2 > 1:
        raise ValueError("box must stay inside the image")
    return [cx, cy, width, height], positive


def _decode_image(image_bytes: bytes):
    from PIL import Image, ImageOps

    if not image_bytes:
        raise ValueError("image is empty")
    image = Image.open(io.BytesIO(image_bytes))
    image.load()
    image = ImageOps.exif_transpose(image)
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise ValueError(f"image exceeds {MAX_IMAGE_PIXELS} pixels")
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, (255, 255, 255))
        rgb.paste(rgba, mask=rgba.getchannel("A"))
        return rgb
    return image.convert("RGB")


def _canonical_rgba(image, mask, output_size: int, padding_ratio: float = 0.08):
    import numpy as np
    from PIL import Image

    mask = np.asarray(mask, dtype=bool).squeeze()
    if mask.ndim != 2 or mask.shape != (image.height, image.width):
        raise ValueError("mask shape does not match image")
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("mask is empty")

    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    object_side = max(x1 - x0, y1 - y0)
    side = max(2, int(math.ceil(object_side * (1 + 2 * padding_ratio))))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left, top = int(math.floor(cx - side / 2)), int(math.floor(cy - side / 2))
    right, bottom = left + side, top + side

    src_left, src_top = max(0, left), max(0, top)
    src_right, src_bottom = min(image.width, right), min(image.height, bottom)
    dst_left, dst_top = src_left - left, src_top - top

    rgb = np.asarray(image, dtype=np.uint8)
    alpha = mask.astype(np.uint8) * 255
    rgba = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    crop = rgba.crop((src_left, src_top, src_right, src_bottom))
    canvas.paste(crop, (dst_left, dst_top), crop)
    if canvas.size != (output_size, output_size):
        canvas = canvas.resize((output_size, output_size), Image.Resampling.LANCZOS)
    return canvas, {
        "source_bbox_xyxy": [x0, y0, x1, y1],
        "source_mask_fraction": float(mask.mean()),
        "padding_ratio": padding_ratio,
        "output_size": output_size,
    }


@app.function(
    image=cpu_image,
    volumes={"/artifacts": artifacts},
    cpu=2,
    memory=4096,
    timeout=5 * 60,
    max_containers=8,
)
def materialize(
    scene_id: str,
    selection_id: str,
    candidate_id: str,
    output_size: int = DEFAULT_OUTPUT_SIZE,
    include_full_rgba: bool = False,
) -> dict:
    import numpy as np
    from PIL import Image

    output_size = _validate_output_size(output_size)
    candidate_id = _candidate_id(candidate_id)
    scene_path = _scene_path(scene_id)
    root = _selection_root(scene_id, selection_id)
    result_path = root / "result.json"
    masks_path = root / "masks.bin"
    if not scene_path.is_file() or not result_path.is_file() or not masks_path.is_file():
        artifacts.reload()
    if not scene_path.is_file():
        raise FileNotFoundError(f"scene not found: {scene_id}")
    if not result_path.is_file() or not masks_path.is_file():
        raise FileNotFoundError(f"selection not found: {selection_id}")

    result = json.loads(result_path.read_text())
    candidate = next((c for c in result.get("candidates", []) if c.get("candidate_id") == candidate_id), None)
    if candidate is None:
        raise FileNotFoundError(f"candidate not found: {candidate_id}")

    height, width = result["mask_storage"]["shape"]
    bytes_per_mask = int(result["mask_storage"]["bytes_per_mask"])
    mask_index = int(candidate["mask_index"])
    packed = masks_path.read_bytes()
    begin, end = mask_index * bytes_per_mask, (mask_index + 1) * bytes_per_mask
    if end > len(packed):
        raise ValueError("packed mask storage is truncated")
    mask = np.unpackbits(
        np.frombuffer(packed[begin:end], dtype=np.uint8),
        count=height * width,
        bitorder="little",
    ).reshape(height, width).astype(bool)

    image = _decode_image(scene_path.read_bytes())
    if image.size != (width, height):
        raise ValueError("scene dimensions do not match mask storage")

    candidate_root = root / candidate_id
    candidate_root.mkdir(parents=True, exist_ok=True)
    mask_path = candidate_root / "mask.png"
    canonical_path = candidate_root / "canonical.png"
    Image.fromarray(mask.astype(np.uint8) * 255, "L").save(mask_path, compress_level=1)
    canonical, metadata = _canonical_rgba(image, mask, output_size)
    canonical.save(canonical_path, compress_level=1)

    response = {
        "scene_id": scene_id,
        "selection_id": selection_id,
        "candidate_id": candidate_id,
        "mask_path": str(mask_path.relative_to("/artifacts")),
        "canonical_path": str(canonical_path.relative_to("/artifacts")),
        "mask_bytes": mask_path.stat().st_size,
        "canonical_bytes": canonical_path.stat().st_size,
        "canonical": metadata,
    }
    if include_full_rgba:
        alpha = mask.astype(np.uint8) * 255
        rgba_path = candidate_root / "rgba.png"
        Image.fromarray(np.dstack([np.asarray(image, dtype=np.uint8), alpha]), "RGBA").save(
            rgba_path, compress_level=1
        )
        response.update(
            {
                "rgba_path": str(rgba_path.relative_to("/artifacts")),
                "rgba_bytes": rgba_path.stat().st_size,
            }
        )
    artifacts.commit()
    return response


@app.cls(
    image=runtime_image,
    gpu=GPU,
    volumes={"/models": weights, "/artifacts": artifacts},
    timeout=30 * 60,
    scaledown_window=300,
    max_containers=1,
)
class Model:
    @modal.enter()
    def load(self) -> None:
        import torch
        import sam3.model_builder as sam3_builder
        from sam3.model.sam3_image_processor import Sam3Processor

        if not CHECKPOINT.is_file():
            raise FileNotFoundError(f"run sync_weights first: {CHECKPOINT}")
        torch.set_float32_matmul_precision("high")
        torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()

        # SAM 3.1's multiplex checkpoint/config has three detector FPN levels.
        # The generic image builder constructs four, then discards the last via
        # scalp=1. Build on CPU, remove that unused level before loading weights,
        # and set scalp=0 so the effective three features are unchanged.
        self.model = sam3_builder.build_sam3_image_model(
            device="cpu",
            checkpoint_path=None,
            load_from_HF=False,
            enable_inst_interactivity=False,
            compile=False,
        )
        visual = self.model.backbone.vision_backbone
        if len(visual.convs) != 4 or self.model.backbone.scalp != 1:
            raise RuntimeError("unexpected SAM 3 image-backbone layout")
        visual.convs = torch.nn.ModuleList(list(visual.convs[:3]))
        visual.scale_factors = visual.scale_factors[:3]
        self.model.backbone.scalp = 0
        sam3_builder._load_checkpoint(self.model, str(CHECKPOINT))
        self.model = self.model.cuda().eval()
        self.processor = Sam3Processor(self.model, confidence_threshold=0.5)
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - t0
        self.load_peak_allocated_gib = torch.cuda.max_memory_allocated() / 2**30
        self.load_peak_reserved_gib = torch.cuda.max_memory_reserved() / 2**30
        self.scene_cache: OrderedDict[str, tuple[object, dict]] = OrderedDict()

    def _timed(self, fn):
        import torch

        torch.cuda.synchronize()
        t0 = time.perf_counter()
        value = fn()
        torch.cuda.synchronize()
        return value, time.perf_counter() - t0

    def _store_scene(self, scene_id: str, image_bytes: bytes) -> None:
        path = _scene_path(scene_id)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(image_bytes)

    def _image_for_scene(self, scene_id: str):
        cached = self.scene_cache.get(scene_id)
        if cached is not None:
            return cached[0]
        path = _scene_path(scene_id)
        if not path.is_file():
            artifacts.reload()
        if not path.is_file():
            raise FileNotFoundError(f"scene not found: {scene_id}")
        return _decode_image(path.read_bytes())

    def _state_for(self, scene_id: str, image):
        import torch

        cached = self.scene_cache.pop(scene_id, None)
        if cached is not None:
            self.scene_cache[scene_id] = cached
            return cached[1], 0.0, True
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            state, encode_s = self._timed(lambda: self.processor.set_image(image))
        self.scene_cache[scene_id] = (image, state)
        while len(self.scene_cache) > SCENE_CACHE_SIZE:
            self.scene_cache.popitem(last=False)
            torch.cuda.empty_cache()
        return state, encode_s, False

    def _persist_masks(self, image, output, scene_id: str, concept: str, kind: str, max_candidates: int):
        import numpy as np

        scores = output["scores"].detach().float().cpu().numpy()
        boxes = output["boxes"].detach().float().cpu().numpy()
        masks = output["masks"].detach().cpu().numpy()
        order = np.argsort(-scores)[:max_candidates]

        selection_id = uuid.uuid4().hex
        root = _selection_root(scene_id, selection_id)
        root.mkdir(parents=True, exist_ok=True)
        candidates = []
        stored_masks = []
        for rank, idx in enumerate(order):
            mask = np.asarray(masks[idx]).squeeze().astype(bool)
            if not mask.any():
                continue
            mask_index = len(stored_masks)
            stored_masks.append(mask)
            candidate_id = f"c{rank:02d}"
            ys, xs = np.nonzero(mask)
            box = [float(v) for v in boxes[idx]]
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "rank": rank,
                    "mask_index": mask_index,
                    "score": float(scores[idx]),
                    "mask_pixels": int(mask.sum()),
                    "mask_fraction": float(mask.mean()),
                    "mask_bbox_xyxy": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
                    "model_bbox_xyxy": box,
                    "model_bbox_xyxy_norm": [
                        min(1.0, max(0.0, box[0] / image.width)),
                        min(1.0, max(0.0, box[1] / image.height)),
                        min(1.0, max(0.0, box[2] / image.width)),
                        min(1.0, max(0.0, box[3] / image.height)),
                    ],
                }
            )

        if stored_masks:
            flat = np.stack(stored_masks, axis=0).reshape(len(stored_masks), -1)
            packed = np.packbits(flat, axis=1, bitorder="little")
            masks_path = root / "masks.bin"
            masks_path.write_bytes(packed.tobytes())
            mask_storage = {
                "path": str(masks_path.relative_to("/artifacts")),
                "encoding": "numpy.packbits",
                "bitorder": "little",
                "shape": [image.height, image.width],
                "count": len(stored_masks),
                "bytes_per_mask": int(packed.shape[1]),
                "bytes": masks_path.stat().st_size,
            }
        else:
            mask_storage = {
                "path": None,
                "encoding": "numpy.packbits",
                "bitorder": "little",
                "shape": [image.height, image.width],
                "count": 0,
                "bytes_per_mask": 0,
                "bytes": 0,
            }

        return {
            "scene_id": scene_id,
            "selection_id": selection_id,
            "concept": concept,
            "kind": kind,
            "image_size": [image.width, image.height],
            "candidate_count": len(candidates),
            "mask_storage": mask_storage,
            "candidates": candidates,
        }, root

    def _finish(self, result: dict, root: Path) -> dict:
        result_path = root / "result.json"
        result["result_path"] = str(result_path.relative_to("/artifacts"))
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        artifacts.commit()
        return result

    @modal.method()
    def segment(
        self,
        image_bytes: bytes,
        concept: str,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> dict:
        import torch

        concept = _validate_concept(concept)
        max_candidates = _validate_max_candidates(max_candidates)
        image = _decode_image(image_bytes)
        scene_id = hashlib.sha256(image_bytes).hexdigest()
        self._store_scene(scene_id, image_bytes)
        state, encode_s, cache_hit = self._state_for(scene_id, image)

        torch.cuda.reset_peak_memory_stats()
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            self.processor.reset_all_prompts(state)
            output, prompt_s = self._timed(
                lambda: self.processor.set_text_prompt(prompt=concept, state=state)
            )
        result, root = self._persist_masks(image, output, scene_id, concept, "text", max_candidates)
        result.update(
            {
                "gpu": torch.cuda.get_device_name(),
                "model_load_s": self.load_s,
                "encode_s": encode_s,
                "scene_cache_hit": cache_hit,
                "prompt_s": prompt_s,
                "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
                "peak_reserved_gib": torch.cuda.max_memory_reserved() / 2**30,
                "sam3_code_commit": SAM3_COMMIT,
                "sam31_revision": SAM31_REVISION,
            }
        )
        return self._finish(result, root)

    @modal.method()
    def refine(
        self,
        scene_id: str,
        concept: str,
        boxes: list[dict],
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> dict:
        import torch

        concept = _validate_concept(concept)
        max_candidates = _validate_max_candidates(max_candidates)
        if not boxes or len(boxes) > 16:
            raise ValueError("boxes must contain between 1 and 16 prompts")
        parsed_boxes = [_box_from_dict(box) for box in boxes]
        image = self._image_for_scene(scene_id)
        state, encode_s, cache_hit = self._state_for(scene_id, image)

        torch.cuda.reset_peak_memory_stats()
        box_timings = []
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            self.processor.reset_all_prompts(state)
            output, text_s = self._timed(
                lambda: self.processor.set_text_prompt(prompt=concept, state=state)
            )
            for box, positive in parsed_boxes:
                output, elapsed = self._timed(
                    lambda b=box, p=positive: self.processor.add_geometric_prompt(
                        box=b, label=p, state=state
                    )
                )
                box_timings.append(elapsed)

        result, root = self._persist_masks(image, output, scene_id, concept, "refine", max_candidates)
        result.update(
            {
                "gpu": torch.cuda.get_device_name(),
                "model_load_s": self.load_s,
                "encode_s": encode_s,
                "scene_cache_hit": cache_hit,
                "text_prompt_s": text_s,
                "box_prompt_s": box_timings,
                "prompt_s": text_s + sum(box_timings),
                "boxes": [
                    {"cx": b[0], "cy": b[1], "width": b[2], "height": b[3], "positive": positive}
                    for b, positive in parsed_boxes
                ],
                "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
                "peak_reserved_gib": torch.cuda.max_memory_reserved() / 2**30,
                "sam3_code_commit": SAM3_COMMIT,
                "sam31_revision": SAM31_REVISION,
            }
        )
        return self._finish(result, root)
