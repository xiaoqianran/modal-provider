from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import modal

APP_NAME = "modal-3d-pixal3d"
GPU = "L40S"
MODEL_ID = "TencentARC/Pixal3D"
MODEL_DIR = "/models/Pixal3D"
HF_HOME = "/models/hf"
TORCH_HOME = "/models/torch"
SRC = "/opt/Pixal3D"
TAG = "pixal3d-py310-cu124-torch260-sm89-v1"
WHEELS_URL = f"https://github.com/xiaoqianran/modal-build/releases/download/{TAG}/{TAG}.wheels.zip"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-pixal3d-weights", create_if_missing=True)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)

download_image = modal.Image.debian_slim(python_version="3.10").uv_pip_install(
    "huggingface_hub>=0.34,<1"
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-runtime-ubuntu22.04", add_python="3.10")
    .apt_install("git", "curl", "unzip", "libgl1", "libglib2.0-0", "ffmpeg", "libgomp1", "gcc")
    .run_commands(
        "python -m pip install --upgrade uv",
        "uv pip install --system torch==2.6.0 torchvision==0.21.0 triton==3.2.0 --index-url https://download.pytorch.org/whl/cu124",
        "uv pip install --system pillow==12.0.0 imageio==2.37.2 imageio-ffmpeg==0.6.0 tqdm==4.67.1 easydict==1.13 opencv-python-headless==4.12.0.88 trimesh==4.10.1 transformers==4.57.3 zstandard==0.25.0 kornia==0.8.2 timm==1.0.22 diffusers==0.37.1 accelerate==1.13.0 plyfile==1.1.3 safetensors numpy scipy 'huggingface_hub>=0.34,<1'",
        "uv pip install --system https://github.com/LDYang694/Storages/releases/download/20260430/utils3d-0.0.2-py3-none-any.whl",
        "git clone https://github.com/microsoft/MoGe.git /opt/MoGe && git -C /opt/MoGe checkout 74fbce054ebed49800de42d0ad0e83495065719a && uv pip install --system /opt/MoGe",
        "git clone https://github.com/valeoai/NAF.git /opt/NAF && git -C /opt/NAF checkout 37f2dfc180f2de53d98bd601109c0da0dd6b0f43",
        f"curl -fL '{WHEELS_URL}' -o /tmp/wheels.zip && mkdir -p /tmp/wheels && unzip -q /tmp/wheels.zip -d /tmp/wheels && uv pip install --system --no-deps /tmp/wheels/*.whl",
        "git clone https://github.com/TencentARC/Pixal3D.git /opt/Pixal3D && git -C /opt/Pixal3D checkout cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af",
        "python - <<'PY'\np='/opt/Pixal3D/pixal3d/trainers/flow_matching/mixins/image_conditioned_proj.py'\ns=open(p).read().replace('torch.hub.load(\\n                \"valeoai/NAF\", \"naf\", pretrained=True, device=device, trust_repo=True\\n            )','torch.hub.load(\\n                \"/opt/NAF\", \"naf\", pretrained=True, device=device, source=\"local\"\\n            )')\nopen(p,'w').write(s)\nPY",
        "uv pip install --system 'huggingface_hub>=0.34,<1'",
        "python -c \"import huggingface_hub, transformers; assert huggingface_hub.__version__.startswith('0.'), (huggingface_hub.__version__, transformers.__version__)\"",
    )
    .env(
        {
            "PYTHONPATH": SRC,
            "HF_HOME": HF_HOME,
            "HUGGINGFACE_HUB_CACHE": f"{HF_HOME}/hub",
            "TORCH_HOME": TORCH_HOME,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "ATTN_BACKEND": "sdpa",
            "TORCH_CUDA_ARCH_LIST": "8.9",
            "NATTEN_CUDA_ARCH": "8.9",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            "FLEX_GEMM_AUTOTUNER_VERBOSE": "0",
            "CC": "/usr/bin/gcc",
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
    Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)
    Path(HF_HOME).mkdir(parents=True, exist_ok=True)
    snapshot_download(MODEL_ID, local_dir=MODEL_DIR)
    for repo in (
        "camenduru/dinov3-vitl16-pretrain-lvd1689m",
        "Ruicheng/moge-2-vitl",
    ):
        snapshot_download(repo, cache_dir=f"{HF_HOME}/hub")

    # Replace gated/default RMBG with the cached public BiRefNet model.
    pipeline = Path(MODEL_DIR) / "pipeline.json"
    data = json.loads(pipeline.read_text())
    data["args"]["rembg_model"] = {
        "name": "BiRefNet",
        "args": {"model_name": "ZhengPeng7/BiRefNet"},
    }
    pipeline.write_text(json.dumps(data, indent=2) + "\n")

    naf_ckpt = Path(TORCH_HOME) / "hub/checkpoints/naf_release.pth"
    naf_ckpt.parent.mkdir(parents=True, exist_ok=True)
    if not naf_ckpt.exists():
        urllib.request.urlretrieve(
            "https://github.com/valeoai/NAF/releases/download/model/naf_release.pth",
            naf_ckpt,
        )
    weights.commit()
    total = sum(p.stat().st_size for p in Path("/models").rglob("*") if p.is_file())
    return {"elapsed_s": time.perf_counter() - t0, "bytes": total}


class _Vram:
    def __init__(self):
        self.stop_event = threading.Event()
        self.peak_mib = 0.0

    def start(self):
        def loop():
            while not self.stop_event.wait(0.5):
                try:
                    out = subprocess.check_output(
                        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                        text=True,
                    )
                    self.peak_mib = max(self.peak_mib, float(out.splitlines()[0]))
                except (subprocess.SubprocessError, ValueError, IndexError):
                    continue

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def stop(self) -> float:
        self.stop_event.set()
        self.thread.join(timeout=2)
        return self.peak_mib / 1024


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

        sys.path.insert(0, SRC)
        os.chdir(SRC)
        import torch
        from inference import IMAGE_COND_CONFIGS, build_image_cond_model, load_moge_model
        from pixal3d.pipelines import Pixal3DImageTo3DPipeline, rembg

        class _NoopRemBg:
            def __init__(self, **_):
                pass

            def to(self, _device):
                return self

            cuda = cpu = to

            def __call__(self, _image):
                raise RuntimeError("Pixal3D worker requires a pre-matted RGBA input")

        rembg.BiRefNet = _NoopRemBg
        t0 = time.perf_counter()
        self.pipe = Pixal3DImageTo3DPipeline.from_pretrained(MODEL_DIR)
        self.pipe.image_cond_model_ss = build_image_cond_model(IMAGE_COND_CONFIGS["ss"])
        self.pipe.image_cond_model_shape_512 = build_image_cond_model(IMAGE_COND_CONFIGS["shape_512"])
        self.pipe.image_cond_model_shape_1024 = build_image_cond_model(IMAGE_COND_CONFIGS["shape_1024"])
        self.pipe.image_cond_model_tex_1024 = build_image_cond_model(IMAGE_COND_CONFIGS["tex_1024"])
        self.pipe.low_vram = False
        self.pipe.cuda()
        for name in (
            "image_cond_model_ss",
            "image_cond_model_shape_512",
            "image_cond_model_shape_1024",
            "image_cond_model_tex_1024",
        ):
            model = getattr(self.pipe, name).cuda()
            if getattr(model, "use_naf_upsample", False):
                model._load_naf()
        self.moge = load_moge_model(device="cpu")
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - t0

    @modal.method()
    def generate(self, image_bytes: bytes, seed: int = 42, fov: float | None = None) -> dict:
        import numpy as np
        import o_voxel
        import torch
        from inference import distance_from_fov, get_camera_params_wild_moge
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))
        image = self.pipe.preprocess_image(image)
        work = Path("/tmp/pixal3d")
        work.mkdir(exist_ok=True)
        temp = work / "input.png"
        image.save(temp)

        if fov is None:
            self.moge.cuda()
            camera = get_camera_params_wild_moge(str(temp), self.moge, device="cuda")
            self.moge.cpu()
            torch.cuda.empty_cache()
        else:
            grid = torch.tensor([-1.0, 0.0, 0.0])
            distance = distance_from_fov(
                fov,
                grid,
                torch.tensor([0, 511]),
                1.0,
                512,
            )["distance_from_x"]
            camera = {"camera_angle_x": fov, "distance": distance, "mesh_scale": 1.0}

        vram = _Vram()
        vram.start()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        try:
            meshes, (_, _, resolution) = self.pipe.run(
                image,
                camera_params=camera,
                seed=seed,
                preprocess_image=False,
                return_latent=True,
                pipeline_type="1024_cascade",
            )
            mesh = meshes[0]
            glb = o_voxel.postprocess.to_glb(
                vertices=mesh.vertices,
                faces=mesh.faces,
                attr_volume=mesh.attrs,
                coords=mesh.coords,
                attr_layout=self.pipe.pbr_attr_layout,
                grid_size=resolution,
                aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
                decimation_target=1_000_000,
                texture_size=4096,
                remesh=True,
                remesh_band=1,
                remesh_project=0,
                use_tqdm=False,
            )
            glb.apply_transform(
                np.array(
                    [[-1, 0, 0, 0], [0, 0, -1, 0], [0, -1, 0, 0], [0, 0, 0, 1]],
                    dtype=np.float64,
                )
            )
            path = work / "output.glb"
            glb.export(path, extension_webp=True)
            torch.cuda.synchronize()
            inference_s = time.perf_counter() - t0
        finally:
            peak_vram_gb = vram.stop()

        name = f"pixal3d/{uuid.uuid4().hex}.glb"
        dst = Path("/artifacts") / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        artifacts.commit()
        return {
            "model": "pixal3d",
            "gpu": GPU,
            "resolution": 1024,
            "seed": seed,
            "artifact": name,
            "glb_bytes": dst.stat().st_size,
            "load_s": self.load_s,
            "inference_s": inference_s,
            "peak_vram_gb": peak_vram_gb,
        }
