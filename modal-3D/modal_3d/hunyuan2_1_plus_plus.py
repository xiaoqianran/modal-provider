from __future__ import annotations

import io
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import modal

from .common import run_generation_job, worker_capability

APP_NAME = "modal-3d-hunyuan"
MODEL_ID = "tencent/Hunyuan3D-2.1"
MODEL_REVISION = "0b94677654c57bb9a6b6845cd7b704ccf551d327"
DINO_ID = "facebook/dinov2-giant"
DINO_REVISION = "611a9d42f2335e0f921f1e313ad3c1b7178d206d"
MODEL_DIR = "/models/Hunyuan3D-2.1"
HF_CACHE = "/models/hf-cache"
REALESRGAN_CKPT = "/models/RealESRGAN_x4plus.pth"
REALESRGAN_SHA256 = "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1"
SRC = "/opt/hunyuan2.1-plus-plus"
FORK = "Archerkattri/hunyuan2.1-plus-plus"
FORK_COMMIT = "9efd760fbec8ab490e68b330225ea1fab10de7fd"
GPU = "L40S"
PAINT_TAG = "hunyuan3d-2.1-paint-py311-cu124-torch251-sm89-v2"
PAINT_BUNDLE_URL = (
    f"https://github.com/xiaoqianran/modal-build/releases/download/{PAINT_TAG}/{PAINT_TAG}.bundle.zip"
)

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-hunyuan21-weights", create_if_missing=True)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)

CAPABILITY = worker_capability(
    "hunyuan2.1-plus-plus",
    "Hunyuan2.1++",
    APP_NAME,
    "完整 Shape + Hunyuan3D-Paint 2.1 PBR；推荐模式使用原生采样",
    {
        "seed": {"type": "integer", "default": 42},
        "acceleration": {
            "type": "string",
            "default": "base",
            "enum": ["base", "dmd"],
        },
        "interval": {"type": "integer", "default": 1, "minimum": 1, "maximum": 12},
        "history": {"type": "integer", "default": 6, "minimum": 4, "maximum": 32},
        "num_inference_steps": {"type": "integer", "default": 50, "minimum": 1, "maximum": 100},
        "paint_remesh": {"type": "boolean", "default": True},
    },
    profile={
        "acceleration": "base",
        "interval": 1,
        "history": 6,
        "num_inference_steps": 50,
        "paint_remesh": True,
    },
    profile_name="推荐 · 官方完整 PBR",
    profile_metadata={
        "quality": {
            "tier": "full_quality",
            "basis": "Tencent Hunyuan3D-2.1 official Shape + Paint defaults",
            "verification": {
                "status": "verified",
                "benchmark": "benchmarks/full-quality-smoke-2026-08-28.json",
            },
        }
    },
    reference_metadata={
        "status": "stale",
        "benchmark": "benchmarks/pages-pinterest-a1-quality-2026-08-24.json",
        "metric": "worker_inference_s",
        "profile_id": "recommended",
        "note": "557.26s reference used paint_remesh=false; re-smoke required for remesh=true",
    },
    output="textured",
    deployment={
        "source": FORK,
        "source_revision": FORK_COMMIT,
        "base_model": MODEL_ID,
        "base_model_revision": MODEL_REVISION,
        "build_artifact": PAINT_TAG,
    },
    warm_seconds=557.26,
    cold_start_seconds=52.88,
    priority=30,
    generation_entrypoint={
        "kind": "class_method",
        "class_name": "Model",
        "method_name": "generate_job",
    },
)

download_image = modal.Image.debian_slim(python_version="3.10").uv_pip_install(
    "huggingface_hub==0.30.2",
    "hf_xet==1.1.9",
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-runtime-ubuntu22.04", add_python="3.11")
    .apt_install(
        "git",
        "curl",
        "unzip",
        "libgl1",
        "libglib2.0-0",
        "libgomp1",
        "libx11-6",
        "libx11-xcb1",
        "libxcb1",
        "libxrender1",
        "libxfixes3",
        "libxext6",
        "libxi6",
        "libxxf86vm1",
        "libsm6",
        "libice6",
        "libxkbcommon0",
        "libxkbcommon-x11-0",
    )
    .uv_pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        index_url="https://download.pytorch.org/whl/cu124",
        uv_version="0.12.5",
    )
    .uv_pip_install(
        "numpy==1.26.4",
        "transformers==4.46.0",
        "diffusers==0.30.0",
        "accelerate==1.1.1",
        "pytorch-lightning==1.9.5",
        "torchmetrics==1.6.0",
        "huggingface-hub==0.30.2",
        "safetensors==0.4.4",
        "scipy==1.14.1",
        "einops==0.8.0",
        "opencv-python-headless==4.10.0.84",
        "imageio==2.36.0",
        "scikit-image==0.24.0",
        "trimesh==4.4.7",
        "pymeshlab==2022.2.post3",
        "omegaconf==2.3.0",
        "pyyaml==6.0.2",
        "Pillow==10.4.0",
        "tqdm==4.66.5",
        "timm==1.0.11",
        "torchdiffeq==0.2.5",
        "pygltflib==1.16.3",
        "xatlas==0.0.9",
        "open3d==0.18.0",
        "realesrgan==0.3.0",
        "basicsr==1.4.2",
        "cupy-cuda12x==13.4.1",
        "bpy==4.3.0",
        uv_version="0.12.5",
    )
    .run_commands(
        f"curl -fL '{PAINT_BUNDLE_URL}' -o /tmp/paint-bundle.zip && "
        "mkdir -p /tmp/paint-bundle && unzip -q /tmp/paint-bundle.zip -d /tmp/paint-bundle && "
        "uv pip install --system --no-deps /tmp/paint-bundle/wheels/*.whl",
        f"git clone https://github.com/{FORK}.git {SRC} && git -C {SRC} checkout {FORK_COMMIT}",
        f"cp /tmp/paint-bundle/native/mesh_inpaint_processor*.so {SRC}/hy3dpaint/DifferentiableRenderer/",
        "python - <<'PY'\n"
        "from pathlib import Path\n"
        "p=Path('/usr/local/lib/python3.11/site-packages/basicsr/data/degradations.py')\n"
        "if p.exists():\n"
        "    s=p.read_text().replace('from torchvision.transforms.functional_tensor import rgb_to_grayscale', 'from torchvision.transforms.functional import rgb_to_grayscale')\n"
        "    p.write_text(s)\n"
        "PY",
        "find /usr/local/lib/python3.11/site-packages/basicsr -type d -name __pycache__ -prune -exec rm -rf '{}' +",
        f'PYTHONPATH={SRC}/hy3dshape:{SRC}/hy3dpaint python -c "from basicsr.data.degradations import rgb_to_grayscale; import realesrgan, custom_rasterizer; from DifferentiableRenderer.MeshRender import meshVerticeInpaint; from textureGenPipeline import Hunyuan3DPaintPipeline; from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline; assert callable(Hunyuan3DDiTFlowMatchingPipeline.disable_hicache)"',
    )
    .env(
        {
            "PYTHONPATH": f"{SRC}/hy3dshape:{SRC}/hy3dpaint",
            "HF_HOME": HF_CACHE,
            "HF_HUB_CACHE": HF_CACHE,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        }
    )
)


def _pin_hf_main(cache_dir: str, repo_id: str, revision: str) -> None:
    repo_cache = Path(cache_dir) / f"models--{repo_id.replace('/', '--')}"
    refs = repo_cache / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(revision)


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
    from huggingface_hub import snapshot_download

    t0 = time.perf_counter()
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=MODEL_DIR,
        allow_patterns=["hunyuan3d-dit-v2-1/*", "hunyuan3d-paintpbr-v2-1/*"],
    )
    # Paint's upstream helper resolves by repo id. Seed the exact pinned snapshots into
    # the offline cache and point refs/main at those commits so runtime cannot drift.
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        cache_dir=HF_CACHE,
        allow_patterns=["hunyuan3d-paintpbr-v2-1/*"],
    )
    _pin_hf_main(HF_CACHE, MODEL_ID, MODEL_REVISION)
    snapshot_download(DINO_ID, revision=DINO_REVISION, cache_dir=HF_CACHE)
    _pin_hf_main(HF_CACHE, DINO_ID, DINO_REVISION)

    import hashlib

    ckpt = Path(REALESRGAN_CKPT)
    if not ckpt.exists():
        import urllib.request

        urllib.request.urlretrieve(
            "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
            ckpt,
        )
    digest = hashlib.sha256(ckpt.read_bytes()).hexdigest()
    if digest != REALESRGAN_SHA256:
        raise RuntimeError(f"RealESRGAN checksum mismatch: {digest}")
    weights.commit()
    total = sum(p.stat().st_size for p in Path("/models").rglob("*") if p.is_file())
    return {
        "elapsed_s": time.perf_counter() - t0,
        "bytes": total,
        "revision": MODEL_REVISION,
        "dino_revision": DINO_REVISION,
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
        import sys

        sys.path.insert(0, f"{SRC}/hy3dshape")
        sys.path.insert(0, f"{SRC}/hy3dpaint")
        os.chdir(SRC)
        import torch
        from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
        from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

        if torch.cuda.get_device_capability() != (8, 9):
            raise RuntimeError(f"expected L40S sm_89, got {torch.cuda.get_device_name()}")

        shape_dir = Path(MODEL_DIR) / "hunyuan3d-dit-v2-1"
        paint_dir = Path(MODEL_DIR) / "hunyuan3d-paintpbr-v2-1"
        if not shape_dir.is_dir() or not paint_dir.is_dir():
            raise RuntimeError(
                "Hunyuan3D weights are not provisioned; run sync_weights before GPU warmup"
            )

        torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        self.shape_pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(MODEL_DIR)
        self.shape_pipe.to("cuda")
        paint_config = Hunyuan3DPaintConfig(max_num_view=6, resolution=512)
        paint_config.multiview_pretrained_path = MODEL_ID
        paint_config.dino_ckpt_path = DINO_ID
        paint_config.realesrgan_ckpt_path = REALESRGAN_CKPT
        self.paint_pipe = Hunyuan3DPaintPipeline(paint_config)
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - t0

    @modal.method()
    def warmup(self) -> dict:
        return {"model": CAPABILITY["id"], "load_s": self.load_s}

    def _generate(
        self,
        image_bytes: bytes,
        seed: int = 42,
        acceleration: str = "base",
        interval: int = 1,
        history: int = 6,
        num_inference_steps: int = 50,
        paint_remesh: bool = True,
    ) -> dict:
        import torch
        from PIL import Image

        if acceleration not in {"base", "dmd"}:
            raise ValueError("acceleration must be base or dmd")
        if not 1 <= interval <= 12:
            raise ValueError("interval must be between 1 and 12")
        if not 4 <= history <= 32:
            raise ValueError("history must be between 4 and 32")
        if not 1 <= num_inference_steps <= 100:
            raise ValueError("num_inference_steps must be between 1 and 100")

        image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        if image.getchannel("A").getextrema()[0] == 255:
            raise ValueError("Hunyuan++ input must be prematted RGBA")

        if acceleration == "base":
            self.shape_pipe.disable_hicache()
        else:
            self.shape_pipe.enable_dmd(interval=interval, history=history)

        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        shape_t0 = time.perf_counter()
        mesh = self.shape_pipe(
            image=image,
            num_inference_steps=num_inference_steps,
            generator=torch.Generator("cuda").manual_seed(seed),
        )[0]
        torch.cuda.synchronize()
        shape_s = time.perf_counter() - shape_t0

        with tempfile.TemporaryDirectory(prefix="hunyuan21-") as temp_dir:
            work = Path(temp_dir)
            shape_path = work / "shape.glb"
            mesh.export(shape_path)
            textured_obj = work / "textured_mesh.obj"

            paint_t0 = time.perf_counter()
            self.paint_pipe(
                mesh_path=str(shape_path),
                image_path=image,
                output_mesh_path=str(textured_obj),
                use_remesh=paint_remesh,
                save_glb=True,
            )
            torch.cuda.synchronize()
            paint_s = time.perf_counter() - paint_t0
            textured_glb = textured_obj.with_suffix(".glb")
            if not textured_glb.is_file() or textured_glb.stat().st_size == 0:
                raise RuntimeError("Hunyuan3D-Paint did not produce a GLB")

            name = f"hunyuan21pp/{uuid.uuid4().hex}.glb"
            path = Path("/artifacts") / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(textured_glb, path)
            artifacts.commit()

        return {
            "model": "hunyuan2.1-plus-plus",
            "fork_commit": FORK_COMMIT,
            "base_model_revision": MODEL_REVISION,
            "gpu": torch.cuda.get_device_name(),
            "seed": seed,
            "acceleration": acceleration,
            "interval": interval,
            "history": history,
            "num_inference_steps": num_inference_steps,
            "artifact": name,
            "glb_bytes": path.stat().st_size,
            "load_s": self.load_s,
            "inference_s": shape_s + paint_s,
            "shape_s": shape_s,
            "paint_s": paint_s,
            "peak_vram_allocated_gb": torch.cuda.max_memory_allocated() / 2**30,
            "peak_vram_reserved_gb": torch.cuda.max_memory_reserved() / 2**30,
            "source_vertices": len(mesh.vertices),
            "source_faces": len(mesh.faces),
            "paint_views": 6,
            "paint_resolution": 512,
            # Upstream saves its 4096 bake downsampled by 2 in save_mesh().
            "texture_size": 2048,
            "paint_remesh": paint_remesh,
        }

    @modal.method()
    def generate_job(self, input_path: str, options: dict | None = None) -> dict:
        """Direct GPU entrypoint: the local client spawns this method.

        Input reading, canonical validation, GLB validation and result
        normalization all happen here so no CPU adapter function is needed.
        """
        return run_generation_job(CAPABILITY["id"], artifacts, self._generate, input_path, options)
