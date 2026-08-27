from __future__ import annotations

import io
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import modal

from .common import register_worker_entrypoint, worker_capability

APP_NAME = "modal-3d-hermit-trellis2-plus-plus"
MODEL_ID = "microsoft/TRELLIS.2-4B"
MODEL_REVISION = "af44b45f2e35a493886929c6d786e563ec68364d"
TRELLIS_IMAGE_ID = "microsoft/TRELLIS-image-large"
TRELLIS_IMAGE_REVISION = "25e0d31ffbebe4b5a97464dd851910efc3002d96"
DINO_ID = "facebook/dinov3-vitl16-pretrain-lvd1689m"
DINO_REVISION = "ea8dc2863c51be0a264bab82070e3e8836b02d51"
MODEL_DIR = "/models/TRELLIS.2-4B"
HF_CACHE = "/models/hf-cache"
SRC_DIR = "/opt/hermit"
GPU = "L40S"
BUILD_TAG = "hermit-trellis2-plus-plus-py311-cu124-torch260-sm89-v2"
WHEELS_URL = f"https://github.com/xiaoqianran/modal-build/releases/download/{BUILD_TAG}/{BUILD_TAG}.wheels.zip"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-trellis2-weights", create_if_missing=True)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)

CAPABILITY = worker_capability(
    "hermit-trellis2-plus-plus",
    "Hermite-TRELLIS2++",
    APP_NAME,
    "PBR 纹理 GLB；官方 remesh/to_glb；质量模式禁用近似采样",
    {
        "seed": {"type": "integer", "default": 42},
        "pipeline_type": {
            "type": "string",
            "default": "1536_cascade",
            "enum": ["1024_cascade", "1536_cascade"],
        },
        "acceleration": {
            "type": "string",
            "default": "base",
            "enum": ["base", "dmd"],
        },
        "texture_size": {
            "type": "integer",
            "default": 4096,
            "enum": [2048, 4096],
        },
    },
    profile={"pipeline_type": "1536_cascade", "acceleration": "base", "texture_size": 4096},
    profile_name="推荐 · 官方高质量",
    profile_metadata={
        "quality": {
            "tier": "full_quality",
            "basis": "microsoft/TRELLIS.2 1536 cascade + stock sampler + 4096 PBR export",
            "verification": {
                "status": "verified",
                "benchmark": "benchmarks/full-quality-smoke-2026-08-28.json",
            },
        }
    },
    reference_metadata={
        "status": "verified",
        "benchmark": "benchmarks/pages-pinterest-a1-quality-2026-08-24.json",
        "metric": "worker_inference_s",
        "profile_id": "recommended",
    },
    output="textured",
    deployment={
        "source": "Archerkattri/hermit-trellis2-plus-plus",
        "source_revision": "2c8402a92ea97c510c09e278fae557771aad774d",
        "build_artifact": BUILD_TAG,
        "base_model": MODEL_ID,
        "base_model_revision": MODEL_REVISION,
    },
    warm_seconds=297.25,
    cold_start_seconds=108.32,
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
        f"curl -fL {WHEELS_URL} -o /tmp/wheels.zip && mkdir -p /tmp/wheels && unzip -q /tmp/wheels.zip -d /tmp/wheels",
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

    snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_dir=MODEL_DIR)
    for repo, revision in (
        (TRELLIS_IMAGE_ID, TRELLIS_IMAGE_REVISION),
        (DINO_ID, DINO_REVISION),
    ):
        snapshot_download(repo, revision=revision, cache_dir=HF_CACHE)

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

        sys.path.insert(0, SRC_DIR)

        import torch
        from trellis2.pipelines import Trellis2ImageTo3DPipeline, rembg

        class _NoopRemBg:
            def __init__(self, **_):
                pass

            def to(self, _device):
                return self

            cuda = cpu = to

            def __call__(self, _image):
                raise RuntimeError("Hermit worker requires a pre-matted RGBA input")

        rembg.BiRefNet = _NoopRemBg
        torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        self.pipe = Trellis2ImageTo3DPipeline.from_pretrained(MODEL_DIR)
        self.pipe.to("cuda")
        # Production quality baseline: restore stock TRELLIS.2 samplers. The DMD
        # accelerated path remains opt-in per request instead of changing topology by default.
        self.pipe.enable_faster("base")
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - t0

    @modal.method()
    def warmup(self) -> dict:
        return {"model": CAPABILITY["id"], "load_s": self.load_s}

    @modal.method()
    def generate(
        self,
        image_bytes: bytes,
        seed: int = 42,
        pipeline_type: str = "1536_cascade",
        acceleration: str = "base",
        texture_size: int = 4096,
    ) -> dict:
        import o_voxel
        import torch
        from PIL import Image

        if pipeline_type not in {"1024_cascade", "1536_cascade"}:
            raise ValueError("pipeline_type must be 1024_cascade or 1536_cascade")
        if acceleration not in {"base", "dmd"}:
            raise ValueError("acceleration must be base or dmd")
        if texture_size not in {2048, 4096}:
            raise ValueError("texture_size must be 2048 or 4096")

        # The fork mutates sampler instances in enable_faster(); configure it for every
        # request so a previous fast request cannot leak into a later quality request.
        if acceleration == "base":
            self.pipe.enable_faster("base")
        else:
            self.pipe.enable_faster()
            self.pipe.sparse_structure_sampler.hicache_backend = "dmd"

        image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        out = self.pipe.run(
            image,
            seed=seed,
            preprocess_image=True,
            pipeline_type=pipeline_type,
        )
        torch.cuda.synchronize()
        generation_s = time.perf_counter() - t0

        mesh = out[0]
        post_t0 = time.perf_counter()
        glb_scene = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=1_000_000,
            texture_size=texture_size,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            verbose=False,
        )
        with tempfile.TemporaryDirectory(prefix="hermit-trellis2-") as temp_dir:
            tmp_glb = Path(temp_dir) / "output.glb"
            glb_scene.export(tmp_glb, extension_webp=True)
            postprocess_s = time.perf_counter() - post_t0

            name = f"trellis2/{uuid.uuid4().hex}.glb"
            path = Path("/artifacts") / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmp_glb, path)
            artifacts.commit()

        voxel_size = float(mesh.voxel_size)
        resolution = round(1.0 / voxel_size) if voxel_size > 0 else None
        return {
            "model": "hermit-trellis2-plus-plus",
            "artifact": name,
            "glb_bytes": path.stat().st_size,
            "load_s": self.load_s,
            "inference_s": generation_s + postprocess_s,
            "generation_s": generation_s,
            "postprocess_s": postprocess_s,
            "peak_vram_allocated_gb": torch.cuda.max_memory_allocated() / 2**30,
            "peak_vram_reserved_gb": torch.cuda.max_memory_reserved() / 2**30,
            "source_vertices": len(mesh.vertices),
            "source_faces": len(mesh.faces),
            "resolution": resolution,
            "pipeline_type": pipeline_type,
            "acceleration": acceleration,
            "texture_size": texture_size,
            "pbr_channels": sorted(mesh.layout),
        }



generate, warmup, register = register_worker_entrypoint(app, artifacts, Model, CAPABILITY)
