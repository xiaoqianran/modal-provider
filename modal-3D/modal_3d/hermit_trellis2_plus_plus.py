from __future__ import annotations

import io
import time
import uuid
from pathlib import Path

import modal

from .common import register_worker_entrypoint, worker_capability

APP_NAME = "modal-3d-hermit-trellis2-plus-plus"
MODEL_ID = "microsoft/TRELLIS.2-4B"
MODEL_DIR = "/models/TRELLIS.2-4B"
HF_CACHE = "/models/hf-cache"
SRC_DIR = "/opt/hermit"
GPU = "L40S"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-trellis2-weights", create_if_missing=True)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)

CAPABILITY = worker_capability(
    "hermit-trellis2-plus-plus",
    "Hermite-TRELLIS2++",
    APP_NAME,
    "1024 cascade 几何；Hermite / DMD",
    {"seed": {"type": "integer", "default": 42}},
    deployment={
        "source": "Archerkattri/hermit-trellis2-plus-plus",
        "source_revision": "2c8402a92ea97c510c09e278fae557771aad774d",
        "build_artifact": "hermit-trellis2-plus-plus-py311-cu124-torch260-sm89-v1",
    },
    warm_seconds=11.98,
    priority=20,
)

download_image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "huggingface_hub>=0.34,<1",
)

# Reproducible CUDA 12.4 / PyTorch 2.6 environment matching TRELLIS.2 upstream.
gpu_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.11")
    .apt_install("git", "curl", "unzip", "libjpeg-dev", "libgl1", "libglib2.0-0")
    .run_commands(
        "python -m pip install --upgrade uv",
        "uv pip install --system torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124",
        "uv pip install --system imageio imageio-ffmpeg tqdm einops easydict opencv-python-headless trimesh transformers huggingface_hub safetensors pandas lpips zstandard kornia timm plyfile",
        "uv pip install --system git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8",
        "curl -fL https://github.com/xiaoqianran/modal-build/releases/download/hermit-trellis2-plus-plus-py311-cu124-torch260-sm89-v1/hermit-trellis2-plus-plus-py311-cu124-torch260-sm89-v1.wheels.zip -o /tmp/wheels.zip && mkdir -p /tmp/wheels && unzip -q /tmp/wheels.zip -d /tmp/wheels",
        "uv pip install --system --no-deps /tmp/wheels/*.whl",
        "git clone https://github.com/Archerkattri/hermit-trellis2-plus-plus.git /opt/hermit && cd /opt/hermit && git checkout 2c8402a92ea97c510c09e278fae557771aad774d",
    )
    .env(
        {
            "PYTHONPATH": SRC_DIR,
            "HF_HOME": HF_CACHE,
            "HF_HUB_CACHE": HF_CACHE,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "ATTN_BACKEND": "flash_attn",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        }
    )
)


@app.function(
    image=download_image,
    volumes={"/models": weights},
    cpu=4,
    memory=16384,
    timeout=60 * 60,
    max_containers=1,
    secrets=[modal.Secret.from_name("huggingface")],
)
def sync_weights() -> dict:
    """CPU-only: populate every HF asset needed by GPU startup."""
    from huggingface_hub import snapshot_download

    t0 = time.perf_counter()
    Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)
    Path(HF_CACHE).mkdir(parents=True, exist_ok=True)

    snapshot_download(MODEL_ID, local_dir=MODEL_DIR)
    for repo in (
        "microsoft/TRELLIS-image-large",
        "facebook/dinov3-vitl16-pretrain-lvd1689m",
        "ZhengPeng7/BiRefNet",
    ):
        snapshot_download(repo, cache_dir=HF_CACHE)

    weights.commit()
    total = sum(p.stat().st_size for p in Path("/models").rglob("*") if p.is_file())
    return {"elapsed_s": time.perf_counter() - t0, "bytes": total}


@app.cls(
    image=gpu_image,
    gpu=GPU,
    volumes={"/models": weights, "/artifacts": artifacts},
    min_containers=0,
    max_containers=1,
    scaledown_window=60,
    timeout=30 * 60,
    startup_timeout=15 * 60,
)
class Model:
    @modal.enter()
    def load(self):
        # Keep GPU startup deterministic: cached weights only, no network fallback.
        import sys
        import types

        sys.path.insert(0, SRC_DIR)
        for name in ("nvdiffrast", "nvdiffrast.torch", "nvdiffrec"):
            sys.modules.setdefault(name, types.ModuleType(name))
        sys.modules["nvdiffrast"].torch = sys.modules["nvdiffrast.torch"]

        import torch
        from trellis2.pipelines import Trellis2ImageTo3DPipeline

        torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        self.pipe = Trellis2ImageTo3DPipeline.from_pretrained(MODEL_DIR)
        self.pipe.to("cuda")
        self.pipe.enable_faster()
        self.pipe.sparse_structure_sampler.hicache_backend = "dmd"
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - t0

    @modal.method()
    def warmup(self) -> dict:
        return {"model": CAPABILITY["id"], "load_s": self.load_s}

    @modal.method()
    def generate(self, image_bytes: bytes, seed: int = 42) -> dict:
        import torch
        import trimesh
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        out = self.pipe.run(
            image,
            seed=seed,
            preprocess_image=True,
            pipeline_type="1024_cascade",
        )
        torch.cuda.synchronize()
        inference_s = time.perf_counter() - t0

        mesh = out[0]
        glb = trimesh.Trimesh(
            vertices=mesh.vertices.detach().cpu().numpy(),
            faces=mesh.faces.detach().cpu().numpy(),
            process=False,
        ).export(file_type="glb")

        name = f"trellis2/{uuid.uuid4().hex}.glb"
        path = Path("/artifacts") / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(glb)
        artifacts.commit()

        return {
            "artifact": name,
            "glb_bytes": len(glb),
            "load_s": self.load_s,
            "inference_s": inference_s,
            "peak_vram_allocated_gb": torch.cuda.max_memory_allocated() / 2**30,
            "peak_vram_reserved_gb": torch.cuda.max_memory_reserved() / 2**30,
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
        }


generate, warmup, register = register_worker_entrypoint(app, artifacts, Model, CAPABILITY)
