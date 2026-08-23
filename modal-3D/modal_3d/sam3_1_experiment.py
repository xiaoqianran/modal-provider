from __future__ import annotations

import io
import time
import uuid
from pathlib import Path

import modal

APP_NAME = "modal-3d-sam31-experiment"
GPU = "L40S"

SAM3_REPO = "facebookresearch/sam3"
SAM3_COMMIT = "8f0b7f4d4e7eda2ed606ebde6702c93359ad01da"
SAM31_REPO = "facebook/sam3.1"
SAM31_REVISION = "daa63191845a41281374e725f4c9e51c7a824460"
SAM31_CHECKPOINT = "sam3.1_multiplex.pt"
SAM3_BASE_REPO = "facebook/sam3"
SAM3_BASE_REVISION = "3c879f39826c281e95690f02c7821c4de09afae7"
SAM3_BASE_CHECKPOINT = "sam3.pt"

SRC = Path("/opt/sam3")
MODEL_DIR = Path("/models/sam31")
CHECKPOINT = MODEL_DIR / SAM31_CHECKPOINT
BASE_CHECKPOINT = MODEL_DIR / SAM3_BASE_CHECKPOINT

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-sam31-experiment-weights", create_if_missing=True)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)


download_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "huggingface_hub==0.35.3",
        "hf_xet==1.6.0",
        uv_version="0.12.5",
    )
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


@app.function(
    image=download_image,
    volumes={"/models": weights},
    cpu=4,
    memory=8192,
    timeout=30 * 60,
    max_containers=1,
    secrets=[modal.Secret.from_name("huggingface")],
)
def sync_base_weights() -> dict:
    from huggingface_hub import hf_hub_download

    t0 = time.perf_counter()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    hf_hub_download(
        SAM3_BASE_REPO,
        filename=SAM3_BASE_CHECKPOINT,
        revision=SAM3_BASE_REVISION,
        local_dir=MODEL_DIR,
    )
    weights.commit()
    return {
        "repo": SAM3_BASE_REPO,
        "revision": SAM3_BASE_REVISION,
        "checkpoint": SAM3_BASE_CHECKPOINT,
        "bytes": BASE_CHECKPOINT.stat().st_size,
        "elapsed_s": time.perf_counter() - t0,
    }


def _save_bundle(image, mask, rel_stem: str) -> dict:
    import numpy as np
    from PIL import Image

    arr = np.asarray(image.convert("RGB"), dtype=np.uint8)
    mask = np.asarray(mask, dtype=bool)
    alpha = (mask.astype(np.uint8) * 255)

    mask_img = Image.fromarray(alpha, mode="L")
    rgba = np.dstack([arr, alpha])
    rgba_img = Image.fromarray(rgba, mode="RGBA")

    overlay = arr.copy()
    tint = np.array([202, 158, 230], dtype=np.uint8)
    overlay[mask] = ((overlay[mask].astype(np.uint16) + tint.astype(np.uint16)) // 2).astype(np.uint8)
    overlay_img = Image.fromarray(overlay, mode="RGB")

    base = Path("/artifacts") / rel_stem
    base.parent.mkdir(parents=True, exist_ok=True)
    paths = {}
    for suffix, img in (("mask", mask_img), ("rgba", rgba_img), ("overlay", overlay_img)):
        path = base.with_name(base.name + f"-{suffix}.png")
        img.save(path, optimize=True)
        paths[suffix] = str(path.relative_to("/artifacts"))
    return paths


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
        from sam3 import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor

        if not CHECKPOINT.is_file():
            raise FileNotFoundError(f"run sync_weights first: {CHECKPOINT}")

        torch.set_float32_matmul_precision("high")
        torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        self.model = build_sam3_image_model(
            checkpoint_path=str(CHECKPOINT),
            load_from_HF=False,
            enable_inst_interactivity=False,
            compile=False,
        )
        self.processor = Sam3Processor(self.model, confidence_threshold=0.5)
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - t0
        self.load_peak_allocated_gib = torch.cuda.max_memory_allocated() / 2**30
        self.load_peak_reserved_gib = torch.cuda.max_memory_reserved() / 2**30

    @modal.method()
    def benchmark(
        self,
        image_bytes: bytes,
        text_prompts: list[str] | None = None,
        seed: int = 42,
    ) -> dict:
        import numpy as np
        import torch
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = image.size
        prompts = text_prompts or [
            "person",
            "chair",
            "table",
            "cup",
            "bottle",
            "bag",
            "shoe",
            "plant",
            "lamp",
            "car",
        ]

        torch.manual_seed(seed)
        torch.cuda.reset_peak_memory_stats()

        def timed(fn):
            torch.cuda.synchronize()
            t0 = time.perf_counter()
            value = fn()
            torch.cuda.synchronize()
            return value, time.perf_counter() - t0

        with torch.autocast("cuda", dtype=torch.bfloat16):
            state, encode_s = timed(lambda: self.processor.set_image(image))

            text_results = []
            best = None
            for prompt in prompts:
                self.processor.reset_all_prompts(state)
                output, latency = timed(
                    lambda p=prompt: self.processor.set_text_prompt(prompt=p, state=state)
                )
                scores = output["scores"].detach().float().cpu().numpy()
                boxes = output["boxes"].detach().float().cpu().numpy()
                masks = output["masks"].detach().cpu().numpy()
                row = {
                    "prompt": prompt,
                    "latency_s": latency,
                    "instances": int(len(scores)),
                    "scores": [float(x) for x in scores[:8]],
                    "boxes_xyxy": [[float(v) for v in box] for box in boxes[:8]],
                }
                text_results.append(row)
                if len(scores):
                    idx = int(np.argmax(scores))
                    candidate = (float(scores[idx]), prompt, boxes[idx], masks[idx], latency)
                    if best is None or candidate[0] > best[0]:
                        best = candidate

            if best is None:
                raise RuntimeError("none of the experiment text prompts detected an object")

            best_score, best_prompt, best_box, best_mask, _ = best
            best_mask = np.asarray(best_mask).squeeze().astype(bool)

            # SAM 3.1's native image interaction is concept + geometric box prompting.
            # Use the native SAM 3.x geometric-prompt path. The SAM 3.1 multiplex
            # checkpoint does not contain the legacy SAM1-style interactive head.
            x0, y0, x1, y1 = [float(v) for v in best_box]
            native_box = [
                ((x0 + x1) / 2) / width,
                ((y0 + y1) / 2) / height,
                (x1 - x0) / width,
                (y1 - y0) / height,
            ]
            def run_native_box(box_norm):
                self.processor.reset_all_prompts(state)
                output, latency = timed(
                    lambda: self.processor.add_geometric_prompt(
                        box=box_norm, label=True, state=state
                    )
                )
                masks = output["masks"].detach().cpu().numpy()
                scores = output["scores"].detach().float().cpu().numpy()
                ious = []
                for candidate in masks:
                    candidate = np.asarray(candidate).squeeze().astype(bool)
                    union = np.logical_or(candidate, best_mask).sum()
                    inter = np.logical_and(candidate, best_mask).sum()
                    ious.append(float(inter / union) if union else 0.0)
                if ious:
                    idx = int(np.argmax(ious))
                    mask = np.asarray(masks[idx]).squeeze().astype(bool)
                    return mask, float(scores[idx]), ious[idx], latency, int(len(scores))
                return np.zeros_like(best_mask), 0.0, 0.0, latency, 0

            native_mask, native_score, native_iou, native_box_s, native_instances = run_native_box(native_box)

            cx, cy, bw, bh = native_box
            raw_variants = {
                "exact": (cx, cy, bw, bh),
                "expand_20pct": (cx, cy, bw * 1.2, bh * 1.2),
                "shrink_15pct": (cx, cy, bw * 0.85, bh * 0.85),
                "shift_x_10pct": (cx + bw * 0.10, cy, bw, bh),
                "shift_y_10pct": (cx, cy + bh * 0.10, bw, bh),
            }
            def run_text_box(box_norm):
                self.processor.reset_all_prompts(state)
                _, text_latency = timed(
                    lambda: self.processor.set_text_prompt(prompt=best_prompt, state=state)
                )
                output, box_latency = timed(
                    lambda: self.processor.add_geometric_prompt(
                        box=box_norm, label=True, state=state
                    )
                )
                masks = output["masks"].detach().cpu().numpy()
                scores = output["scores"].detach().float().cpu().numpy()
                ious = []
                for candidate in masks:
                    candidate = np.asarray(candidate).squeeze().astype(bool)
                    union = np.logical_or(candidate, best_mask).sum()
                    inter = np.logical_and(candidate, best_mask).sum()
                    ious.append(float(inter / union) if union else 0.0)
                if ious:
                    idx = int(np.argmax(ious))
                    return float(scores[idx]), ious[idx], text_latency, box_latency, int(len(scores))
                return 0.0, 0.0, text_latency, box_latency, 0

            text_box_robustness = []
            box_robustness = []
            for variant, (vcx, vcy, vbw, vbh) in raw_variants.items():
                vbw = min(max(vbw, 1 / width), 1.0)
                vbh = min(max(vbh, 1 / height), 1.0)
                vcx = min(max(vcx, vbw / 2), 1 - vbw / 2)
                vcy = min(max(vcy, vbh / 2), 1 - vbh / 2)
                box_norm = [vcx, vcy, vbw, vbh]
                if variant == "exact":
                    score, iou, latency, instances = native_score, native_iou, native_box_s, native_instances
                else:
                    _, score, iou, latency, instances = run_native_box(box_norm)
                box_robustness.append({
                    "variant": variant, "box_cxcywh_norm": box_norm,
                    "latency_s": latency, "instances": instances,
                    "best_score": score, "best_iou_to_text": iou,
                })
                t_score, t_iou, t_text_s, t_box_s, t_instances = run_text_box(box_norm)
                text_box_robustness.append({
                    "variant": variant, "box_cxcywh_norm": box_norm,
                    "text_latency_s": t_text_s, "box_latency_s": t_box_s,
                    "total_prompt_latency_s": t_text_s + t_box_s,
                    "instances": t_instances, "best_score": t_score,
                    "best_iou_to_text": t_iou,
                })

            if not best_mask.any():
                raise RuntimeError("best text mask is empty")

        run_id = uuid.uuid4().hex
        base = f"sam31-experiment/{run_id}"
        paths = {
            "text": _save_bundle(image, best_mask, f"{base}/text-{best_prompt}"),
            "native_box": _save_bundle(image, native_mask, f"{base}/native-box"),
        }
        artifacts.commit()

        def mask_stats(mask):
            ys, xs = np.nonzero(mask)
            return {
                "pixels": int(mask.sum()),
                "fraction": float(mask.mean()),
                "bbox_xyxy": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
                if len(xs)
                else None,
            }

        return {
            "gpu": torch.cuda.get_device_name(),
            "sam3_code_commit": SAM3_COMMIT,
            "sam31_repo": SAM31_REPO,
            "sam31_revision": SAM31_REVISION,
            "checkpoint": SAM31_CHECKPOINT,
            "image_size": [width, height],
            "model_load_s": self.load_s,
            "load_peak_allocated_gib": self.load_peak_allocated_gib,
            "load_peak_reserved_gib": self.load_peak_reserved_gib,
            "encode_s": encode_s,
            "text_results": text_results,
            "selected_text_prompt": best_prompt,
            "selected_text_score": best_score,
            "selected_text_mask": mask_stats(best_mask),
            "native_box_cxcywh_norm": native_box,
            "native_box_s": native_box_s,
            "native_box_instances": native_instances,
            "native_box_robustness": box_robustness,
            "text_box_robustness": text_box_robustness,
            "native_box_best_score": native_score,
            "native_box_best_iou_to_text": native_iou,
            "native_box_mask": mask_stats(native_mask),
            "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
            "peak_reserved_gib": torch.cuda.max_memory_reserved() / 2**30,
            "artifacts": paths,
        }


@app.cls(
    image=runtime_image,
    gpu=GPU,
    volumes={"/models": weights},
    timeout=30 * 60,
    scaledown_window=300,
    max_containers=1,
)
class BaseControl:
    @modal.enter()
    def load(self) -> None:
        import torch
        from sam3 import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor

        if not BASE_CHECKPOINT.is_file():
            raise FileNotFoundError(f"run sync_base_weights first: {BASE_CHECKPOINT}")
        torch.set_float32_matmul_precision("high")
        torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        self.model = build_sam3_image_model(
            checkpoint_path=str(BASE_CHECKPOINT),
            load_from_HF=False,
            enable_inst_interactivity=True,
            compile=False,
        )
        self.processor = Sam3Processor(self.model, confidence_threshold=0.5)
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - t0
        self.load_peak_gib = torch.cuda.max_memory_allocated() / 2**30

    @modal.method()
    def probe(self, image_bytes: bytes, text_prompts: list[str] | None = None) -> dict:
        import numpy as np
        import torch
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = image.size
        prompts = text_prompts or ["person", "chair", "table", "cup", "bottle", "bag", "shoe", "plant", "lamp", "car"]

        def timed(fn):
            torch.cuda.synchronize()
            t0 = time.perf_counter()
            value = fn()
            torch.cuda.synchronize()
            return value, time.perf_counter() - t0

        with torch.autocast("cuda", dtype=torch.bfloat16):
            state, encode_s = timed(lambda: self.processor.set_image(image))
            rows = []
            best = None
            for prompt in prompts:
                self.processor.reset_all_prompts(state)
                out, latency = timed(lambda p=prompt: self.processor.set_text_prompt(prompt=p, state=state))
                scores = out["scores"].detach().float().cpu().numpy()
                masks = out["masks"].detach().cpu().numpy()
                boxes = out["boxes"].detach().float().cpu().numpy()
                rows.append({"prompt": prompt, "instances": int(len(scores)), "latency_s": latency})
                if len(scores):
                    idx = int(np.argmax(scores))
                    candidate = (float(scores[idx]), prompt, boxes[idx], masks[idx])
                    if best is None or candidate[0] > best[0]:
                        best = candidate
            if best is None:
                raise RuntimeError("no text object found")
            score, prompt, best_box, best_mask = best
            best_mask = np.asarray(best_mask).squeeze().astype(bool)
            ys, xs = np.nonzero(best_mask)
            point = np.array([[float(xs.mean()), float(ys.mean())]], dtype=np.float32)
            labels = np.array([1], dtype=np.int32)
            box = np.asarray(best_box, dtype=np.float32).reshape(1, 4)
            (pm, ps, _), point_s = timed(lambda: self.model.predict_inst(
                state, point_coords=point, point_labels=labels, multimask_output=True
            ))
            pi = int(np.argmax(ps)); point_mask = np.asarray(pm[pi]).squeeze().astype(bool)
            (bm, bs, _), box_s = timed(lambda: self.model.predict_inst(
                state, point_coords=None, point_labels=None, box=box, multimask_output=False
            ))
            bi = int(np.argmax(bs)); box_mask = np.asarray(bm[bi]).squeeze().astype(bool)

        def iou(a, b):
            union = np.logical_or(a, b).sum(); inter = np.logical_and(a, b).sum()
            return float(inter / union) if union else 0.0
        return {
            "repo": SAM3_BASE_REPO, "revision": SAM3_BASE_REVISION,
            "checkpoint": SAM3_BASE_CHECKPOINT, "gpu": torch.cuda.get_device_name(),
            "load_s": self.load_s, "load_peak_gib": self.load_peak_gib,
            "encode_s": encode_s, "text_results": rows,
            "selected_prompt": prompt, "selected_score": score,
            "text_fraction": float(best_mask.mean()),
            "point_s": point_s, "point_score": float(ps[pi]),
            "point_fraction": float(point_mask.mean()), "point_iou_to_text": iou(point_mask, best_mask),
            "box_s": box_s, "box_score": float(bs[bi]),
            "box_fraction": float(box_mask.mean()), "box_iou_to_text": iou(box_mask, best_mask),
            "peak_gib": torch.cuda.max_memory_allocated() / 2**30,
        }
