from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import modal

from .common import ARTIFACT_VOLUME
from .operation_runner import validate_file
from .operations import (
    MIMES,
    RESULT_CONTRACT,
    confined,
    digest_file,
    options_for,
    request_key,
    revision_for,
    validate_descriptor,
    validate_input_names,
)

APP_NAME = "modal-3d-hunyuan2mv"
GPU = "L40S"

SOURCE_REPO = "Tencent-Hunyuan/Hunyuan3D-2"
SOURCE_REVISION = "f8db63096c8282cb27354314d896feba5ba6ff8a"
SRC = "/opt/hunyuan3d-2"

MODEL_ID = "tencent/Hunyuan3D-2mv"
MODEL_REVISION = "3a761b539b29fe4ff64714813aa9560fd66f5de0"
MODEL_ROOT = "/models/Hunyuan3D-2mv"
SUBFOLDER = "hunyuan3d-dit-v2-mv"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-hunyuan2mv-weights", create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)

download_image = modal.Image.debian_slim(python_version="3.11").uv_pip_install(
    "huggingface_hub==0.30.2",
    "hf_xet==1.1.9",
    uv_version="0.12.5",
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-runtime-ubuntu22.04", add_python="3.11")
    .apt_install("git", "libgl1", "libglib2.0-0", "libgomp1")
    .uv_pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        index_url="https://download.pytorch.org/whl/cu124",
        uv_version="0.12.5",
    )
    .uv_pip_install(
        "numpy==1.26.4",
        "diffusers==0.32.2",
        "transformers==4.48.3",
        "accelerate==1.2.1",
        "einops==0.8.0",
        "opencv-python-headless==4.10.0.84",
        "omegaconf==2.3.0",
        "trimesh==4.4.7",
        "pymeshlab==2023.12.post3",
        "pygltflib==1.16.3",
        "xatlas==0.0.9",
        "scikit-image==0.24.0",
        "safetensors==0.4.5",
        "Pillow==10.4.0",
        "PyYAML==6.0.2",
        "tqdm==4.67.1",
        uv_version="0.12.5",
    )
    .run_commands(
        f"git clone --filter=blob:none https://github.com/{SOURCE_REPO}.git {SRC} && "
        f"git -C {SRC} checkout {SOURCE_REVISION}",
        f'PYTHONPATH={SRC} python -c "from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline; '
        'print(Hunyuan3DDiTFlowMatchingPipeline.__name__)"',
    )
    .env(
        {
            "PYTHONPATH": SRC,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            "PYTHONUNBUFFERED": "1",
        }
    )
)


@app.function(
    image=download_image,
    volumes={"/models": weights},
    cpu=4,
    memory=8192,
    timeout=60 * 60,
    max_containers=1,
)
def sync_weights() -> dict:
    from huggingface_hub import snapshot_download

    started = time.perf_counter()
    path = snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=MODEL_ROOT,
        allow_patterns=[
            f"{SUBFOLDER}/config.yaml",
            f"{SUBFOLDER}/model.fp16.safetensors",
        ],
    )
    required = [
        Path(MODEL_ROOT) / SUBFOLDER / "config.yaml",
        Path(MODEL_ROOT) / SUBFOLDER / "model.fp16.safetensors",
    ]
    for item in required:
        if not item.is_file() or item.stat().st_size == 0:
            raise FileNotFoundError(item)
    weights.commit()
    return {
        "path": path,
        "bytes": sum(item.stat().st_size for item in required),
        "elapsed_s": time.perf_counter() - started,
        "model_revision": MODEL_REVISION,
    }


def _checked_image(root: Path, value: dict) -> tuple[dict, Path]:
    desc = validate_descriptor(value)
    if desc["mime"] != MIMES[".png"]:
        raise ValueError("Hunyuan3D-2mv inputs must be PNG")
    path = confined(root, desc["path"])
    validate_file(path, MIMES[".png"])
    if path.stat().st_size != desc["bytes"] or digest_file(path) != desc["sha256"]:
        raise ValueError("multi-view image integrity mismatch")
    return desc, path


def _descriptor(path: Path, role: str, destination: Path, root: Path) -> dict:
    mime = MIMES[path.suffix]
    validate_file(path, mime)
    digest = digest_file(path)
    return {
        "id": f"art_{digest}",
        "role": role,
        "mime": mime,
        "mediaType": mime,
        "bytes": path.stat().st_size,
        "sha256": digest,
        "digest": f"sha256:{digest}",
        "filename": path.name,
        "path": (destination / path.name).relative_to(root).as_posix(),
    }


@app.cls(
    image=runtime_image,
    gpu=GPU,
    volumes={"/models": weights, "/artifacts": artifacts},
    min_containers=0,
    max_containers=1,
    scaledown_window=120,
    timeout=30 * 60,
    startup_timeout=15 * 60,
)
class Model:
    @modal.enter()
    def load(self):
        import torch
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

        model_dir = Path(MODEL_ROOT) / SUBFOLDER
        if not (model_dir / "config.yaml").is_file() or not (
            model_dir / "model.fp16.safetensors"
        ).is_file():
            raise FileNotFoundError(
                "Hunyuan3D-2mv weights are not provisioned; run sync_weights first"
            )

        sys.path.insert(0, SRC)
        os.chdir(SRC)
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        self.pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            MODEL_ROOT,
            subfolder=SUBFOLDER,
            use_safetensors=True,
            variant="fp16",
            device="cuda",
        )
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - started

    @modal.method()
    def run_job(self, request: dict, options: dict | None = None) -> dict:
        import torch
        import trimesh
        from PIL import Image

        started = time.monotonic()
        if not isinstance(request, dict) or request.get("operation") != "multiview_to_3d":
            raise ValueError("Hunyuan3D-2mv worker only supports multiview_to_3d")

        inputs = validate_input_names("multiview_to_3d", request.get("inputs"))
        normalized = options_for("multiview_to_3d", options)

        root = Path("/artifacts").resolve()
        artifacts.reload()
        checked: dict[str, dict] = {}
        image_paths: dict[str, Path] = {}
        for view, value in inputs.items():
            desc, path = _checked_image(root, value)
            checked[view] = desc
            image_paths[view] = path

        hashes = [desc["sha256"] for desc in checked.values()]
        if len(set(hashes)) != len(hashes):
            raise ValueError("multi-view inputs must not contain duplicate images")

        key = request_key("multiview_to_3d", checked, normalized)
        destination = root / "operations" / "multiview_to_3d" / key
        result_path = destination / "result.json"
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            for desc in result["artifacts"]:
                path = confined(root, desc["path"])
                validate_file(path, desc["mime"])
                if digest_file(path) != desc["sha256"]:
                    raise ValueError("cached Hunyuan3D-2mv artifact corrupted")
            return {**result, "cache_hit": True}

        images = {}
        image_meta = {}
        for view in ("front", "left", "back", "right"):
            path = image_paths.get(view)
            if path is None:
                continue
            with Image.open(path) as source:
                source.load()
                image_meta[view] = {
                    "width": source.width,
                    "height": source.height,
                    "mode": source.mode,
                }
                images[view] = source.convert("RGBA").copy()

        if not images:
            raise ValueError("at least one multi-view image is required")

        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        infer_started = time.perf_counter()
        generated = self.pipeline(
            image=images,
            num_inference_steps=normalized["num_inference_steps"],
            guidance_scale=normalized["guidance_scale"],
            octree_resolution=normalized["octree_resolution"],
            num_chunks=normalized["num_chunks"],
            generator=torch.Generator("cuda").manual_seed(normalized["seed"]),
            output_type="trimesh",
            enable_pbar=False,
        )
        torch.cuda.synchronize()
        inference_s = time.perf_counter() - infer_started

        if not generated:
            raise RuntimeError("Hunyuan3D-2mv returned no mesh")
        mesh = generated[0]
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            raise RuntimeError("Hunyuan3D-2mv returned an invalid mesh")

        with tempfile.TemporaryDirectory(prefix="hunyuan2mv-") as temporary:
            work = Path(temporary)
            output_glb = work / "multiview.glb"
            mesh.export(output_glb)
            validate_file(output_glb, MIMES[".glb"])

            views = list(images)
            quality = {
                "schema": "modal-3d.quality-report.v1",
                "backend": "Hunyuan3D-2mv",
                "source_revision": SOURCE_REVISION,
                "model_revision": MODEL_REVISION,
                "subfolder": SUBFOLDER,
                "views": views,
                "view_count": len(views),
                "images": image_meta,
                "options": normalized,
                "vertices": len(mesh.vertices),
                "faces": len(mesh.faces),
                "load_s": self.load_s,
                "inference_s": inference_s,
                "gpu": torch.cuda.get_device_name(),
                "peak_vram_allocated_gb": torch.cuda.max_memory_allocated() / 2**30,
                "peak_vram_reserved_gb": torch.cuda.max_memory_reserved() / 2**30,
                "texture_generated": False,
            }
            quality_path = work / "quality-report.json"
            quality_path.write_text(
                json.dumps(quality, allow_nan=False, indent=2), encoding="utf-8"
            )

            descriptors = [
                _descriptor(output_glb, "primary-glb", destination, root),
                _descriptor(quality_path, "quality-report", destination, root),
            ]
            result = {
                "contract": RESULT_CONTRACT,
                "operation": "multiview_to_3d",
                "revision": revision_for("multiview_to_3d"),
                "request_key": key,
                "inputs": checked,
                "options": normalized,
                "artifacts": descriptors,
                "metrics": {
                    "view_count": len(views),
                    "views": views,
                    "vertices": len(mesh.vertices),
                    "faces": len(mesh.faces),
                    "inference_s": inference_s,
                },
                "timing": {"total_s": time.monotonic() - started},
                "cache_hit": False,
            }

            destination.mkdir(parents=True, exist_ok=True)
            for desc in descriptors:
                shutil.copyfile(work / desc["filename"], destination / desc["filename"])
            pending = destination / "result.pending"
            pending.write_text(
                json.dumps(result, allow_nan=False, indent=2), encoding="utf-8"
            )
            os.replace(pending, result_path)
            artifacts.commit()
            return result
