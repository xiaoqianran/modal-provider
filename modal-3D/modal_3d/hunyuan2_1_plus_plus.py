from __future__ import annotations

import io
import time
import uuid
from pathlib import Path

import modal

APP_NAME = "modal-3d-hunyuan"
MODEL_ID = "tencent/Hunyuan3D-2.1"
MODEL_REVISION = "0b94677654c57bb9a6b6845cd7b704ccf551d327"
MODEL_DIR = "/models/Hunyuan3D-2.1"
SRC = "/opt/hunyuan2.1-plus-plus"
FORK = "Archerkattri/hunyuan2.1-plus-plus"
FORK_COMMIT = "9efd760fbec8ab490e68b330225ea1fab10de7fd"
GPU = "L40S"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-hunyuan21-weights", create_if_missing=True)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)

download_image = modal.Image.debian_slim(python_version="3.10").uv_pip_install(
    "huggingface_hub==0.30.2",
    "hf_xet==1.1.9",
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-runtime-ubuntu22.04", add_python="3.10")
    .apt_install("git", "libgl1", "libglib2.0-0", "libgomp1")
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
        uv_version="0.12.5",
    )
    .run_commands(
        f"git clone https://github.com/{FORK}.git {SRC} && git -C {SRC} checkout {FORK_COMMIT}",
        f"PYTHONPATH={SRC}/hy3dshape python -c \"from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline; assert callable(Hunyuan3DDiTFlowMatchingPipeline.enable_dmd)\"",
    )
    .env(
        {
            "PYTHONPATH": f"{SRC}/hy3dshape",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
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
    from huggingface_hub import snapshot_download

    t0 = time.perf_counter()
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=MODEL_DIR,
        allow_patterns=["hunyuan3d-dit-v2-1/*"],
    )
    weights.commit()
    total = sum(p.stat().st_size for p in Path(MODEL_DIR).rglob("*") if p.is_file())
    return {
        "elapsed_s": time.perf_counter() - t0,
        "bytes": total,
        "revision": MODEL_REVISION,
    }


adapter_image = modal.Image.debian_slim(python_version="3.10")


@app.function(
    image=adapter_image,
    volumes={"/artifacts": artifacts},
    timeout=30 * 60,
    max_containers=1,
)
def generate(input_path: str, options: dict | None = None) -> dict:
    rel = Path(input_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("input_path must be relative to /artifacts")
    path = Path("/artifacts") / rel
    if not path.is_file():
        raise FileNotFoundError(input_path)
    return Model().generate.remote(path.read_bytes(), **dict(options or {}))


@app.cls(
    image=runtime_image,
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
        import sys

        sys.path.insert(0, f"{SRC}/hy3dshape")
        import torch
        from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline

        if torch.cuda.get_device_capability() != (8, 9):
            raise RuntimeError(f"expected L40S sm_89, got {torch.cuda.get_device_name()}")

        torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        self.pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(MODEL_DIR)
        self.pipe.to("cuda")
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - t0

    @modal.method()
    def generate(
        self,
        image_bytes: bytes,
        seed: int = 42,
        interval: int = 3,
        history: int = 6,
        num_inference_steps: int = 50,
    ) -> dict:
        import torch
        from PIL import Image

        if interval < 1:
            raise ValueError("interval must be >= 1")
        if history < 4:
            raise ValueError("history must be >= 4")

        image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        if image.getchannel("A").getextrema()[0] == 255:
            raise ValueError("Hunyuan++ benchmark input must be prematted RGBA")

        self.pipe.enable_dmd(interval=interval, history=history)
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        mesh = self.pipe(
            image=image,
            num_inference_steps=num_inference_steps,
            generator=torch.Generator("cuda").manual_seed(seed),
        )[0]
        torch.cuda.synchronize()
        inference_s = time.perf_counter() - t0

        glb = mesh.export(file_type="glb")
        name = f"hunyuan21pp/{uuid.uuid4().hex}.glb"
        path = Path("/artifacts") / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(glb)
        artifacts.commit()

        return {
            "model": "hunyuan2.1-plus-plus",
            "fork_commit": FORK_COMMIT,
            "base_model_revision": MODEL_REVISION,
            "gpu": torch.cuda.get_device_name(),
            "seed": seed,
            "interval": interval,
            "dmd_forecast": interval > 1,
            "history": history,
            "num_inference_steps": num_inference_steps,
            "artifact": name,
            "glb_bytes": len(glb),
            "load_s": self.load_s,
            "inference_s": inference_s,
            "peak_vram_allocated_gb": torch.cuda.max_memory_allocated() / 2**30,
            "peak_vram_reserved_gb": torch.cuda.max_memory_reserved() / 2**30,
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
        }
