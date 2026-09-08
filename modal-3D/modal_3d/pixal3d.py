from __future__ import annotations

import io
import os
import shutil
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import modal

from .common import (
    ARTIFACT_VOLUME,
    pinned_hf_snapshot,
    run_generation_job,
    worker_capability,
    worker_identity,
)
from .gpu_telemetry import GpuStageProfiler
from .o_voxel_contract import validate_o_voxel_pbr_intermediate
from .pixal3d_patch import STAGE_CACHE_ENV, patch_pixal3d_stage_cache_guard

APP_NAME = "modal-3d-pixal3d"
GPU = "L40S"
MODEL_ID = "TencentARC/Pixal3D"
MODEL_REVISION = "0b31f9160aa400719af409098bff7936a932f726"
DINO_ID = "camenduru/dinov3-vitl16-pretrain-lvd1689m"
DINO_REVISION = "3c276edd87d6f6e569ff0c4400e086807d0f3881"
MOGE_ID = "Ruicheng/moge-2-vitl"
MOGE_REVISION = "39c4d5e957afe587e04eec59dc2bcc3be5ecd968"
MODEL_DIR = "/models/Pixal3D"
HF_HOME = "/models/hf"
TORCH_HOME = "/models/torch"
SRC = "/opt/Pixal3D"
TAG = "pixal3d-py310-cu124-torch260-sm89-v1"
WHEELS_URL = f"https://github.com/xiaoqianran/modal-build/releases/download/{TAG}/{TAG}.wheels.zip"
FLEX_GEMM_CACHE_PATH = (
    "/pixal-cache/sm89-cu124-torch260-pixal-cdbb2bbffbf4/autotune_cache.json"
)

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-pixal3d-weights", create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)
autotune_cache = modal.Volume.from_name("modal-3d-pixal3d-autotune", create_if_missing=True)

CAPABILITY = worker_capability(
    "pixal3d",
    "Pixal3D",
    APP_NAME,
    "完整 PBR 纹理 GLB；1536 cascade + 4096 texture",
    {
        "seed": {"type": "integer", "default": 42},
        "fov": {"type": "number", "default": None, "nullable": True},
        "pipeline_type": {
            "type": "string",
            "default": "1536_cascade",
            "enum": ["1024_cascade", "1536_cascade"],
        },
        "max_num_tokens": {"type": "integer", "default": 49152, "minimum": 32768, "maximum": 65536},
        "texture_size": {"type": "integer", "default": 4096, "enum": [2048, 4096]},
    },
    profile={
        "fov": None,
        "pipeline_type": "1536_cascade",
        "max_num_tokens": 49152,
        "texture_size": 4096,
    },
    profile_name="推荐 · 官方标准高质量",
    profile_metadata={
        "quality": {
            "tier": "full_quality",
            "basis": "TencentARC/Pixal3D standard 1536 cascade + 4096 PBR export",
            "verification": {
                "status": "verified",
                "benchmark": "benchmarks/full-quality-smoke-2026-08-28.json",
            },
        }
    },
    reference_metadata={
        "status": "stale",
        "benchmark": "benchmarks/station-canonical-cold-e2e-2026-09-08.json",
        "metric": "local_artifact_e2e_s",
        "e2e_seconds": 346.83,
        "profile_id": "recommended",
    },
    output="textured",
    deployment={
        "source": MODEL_ID,
        "source_revision": "cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af",
        "build_artifact": TAG,
        "base_model": MODEL_ID,
        "base_model_revision": MODEL_REVISION,
    },
    warm_seconds=241.34,
    cold_start_seconds=105.49,
    priority=30,
    generation_entrypoint={
        "kind": "class_method",
        "class_name": "Model",
        "method_name": "generate_job",
    },
)

download_image = modal.Image.debian_slim(python_version="3.10").uv_pip_install(
    "huggingface_hub>=0.34,<1"
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-runtime-ubuntu22.04", add_python="3.10")
    .apt_install("git", "curl", "unzip", "libgl1", "libglib2.0-0", "ffmpeg", "libgomp1", "gcc")
    .run_commands(
        "python -m pip install uv==0.12.5",
        "uv pip install --system torch==2.6.0 torchvision==0.21.0 triton==3.2.0 --index-url https://download.pytorch.org/whl/cu124",
        "uv pip install --system pillow==12.0.0 imageio==2.37.2 imageio-ffmpeg==0.6.0 tqdm==4.67.1 easydict==1.13 opencv-python-headless==4.12.0.88 trimesh==4.10.1 transformers==4.57.3 zstandard==0.25.0 kornia==0.8.2 timm==1.0.22 diffusers==0.37.1 accelerate==1.13.0 plyfile==1.1.3 safetensors numpy scipy einops 'huggingface_hub>=0.34,<1'",
        "uv pip install --system https://github.com/LDYang694/Storages/releases/download/20260430/utils3d-0.0.2-py3-none-any.whl",
        "git clone https://github.com/microsoft/MoGe.git /opt/MoGe && git -C /opt/MoGe checkout 74fbce054ebed49800de42d0ad0e83495065719a && uv pip install --system /opt/MoGe",
        "git clone https://github.com/valeoai/NAF.git /opt/NAF && git -C /opt/NAF checkout 37f2dfc180f2de53d98bd601109c0da0dd6b0f43",
        f"curl -fL --retry 5 --retry-all-errors --retry-delay 2 '{WHEELS_URL}' -o /tmp/wheels.zip && mkdir -p /tmp/wheels && unzip -q /tmp/wheels.zip -d /tmp/wheels && uv pip install --system --no-deps /tmp/wheels/*.whl",
        "git clone https://github.com/TencentARC/Pixal3D.git /opt/Pixal3D && git -C /opt/Pixal3D checkout cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af",
        "python - <<'PY'\np='/opt/Pixal3D/inference.py'\ns=open(p).read()\nold_cache='os.environ[\"FLEX_GEMM_AUTOTUNE_CACHE_PATH\"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), \'autotune_cache.json\')'\nold_verbose='os.environ[\"FLEX_GEMM_AUTOTUNER_VERBOSE\"] = \'1\''\nassert old_cache in s, 'Pixal3D inference.py cache assignment changed upstream'\nassert old_verbose in s, 'Pixal3D inference.py verbose assignment changed upstream'\ns=s.replace(old_cache, 'os.environ.setdefault(\"FLEX_GEMM_AUTOTUNE_CACHE_PATH\", os.path.join(os.path.dirname(os.path.abspath(__file__)), \'autotune_cache.json\'))')\ns=s.replace(old_verbose, 'os.environ.setdefault(\"FLEX_GEMM_AUTOTUNER_VERBOSE\", \'1\')')\nopen(p,'w').write(s)\nPY",
        "python - <<'PY'\np='/opt/Pixal3D/pixal3d/trainers/flow_matching/mixins/image_conditioned_proj.py'\ns=open(p).read().replace('torch.hub.load(\\n                \"valeoai/NAF\", \"naf\", pretrained=True, device=device, trust_repo=True\\n            )','torch.hub.load(\\n                \"/opt/NAF\", \"naf\", pretrained=True, device=device, source=\"local\"\\n            )')\nopen(p,'w').write(s)\nPY",
        "uv pip install --system 'huggingface_hub>=0.34,<1'",
        "python -c \"import einops, huggingface_hub, transformers; assert huggingface_hub.__version__.startswith('0.'), (huggingface_hub.__version__, transformers.__version__)\"",
    )
    .run_function(patch_pixal3d_stage_cache_guard, args=(SRC,))
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
            "FLEX_GEMM_AUTOTUNE_CACHE_PATH": FLEX_GEMM_CACHE_PATH,
            "FLEX_GEMM_USE_AUTOTUNE_CACHE": "1",
            "FLEX_GEMM_AUTOSAVE_AUTOTUNE_CACHE": "1",
            "FLEX_GEMM_AUTOTUNER_VERBOSE": "0",
            "PIXAL3D_PROFILE": "1",
            "PIXAL3D_TELEMETRY_INTERVAL_S": "0.5",
            "PIXAL3D_KEEP_MOGE_ON_GPU": "0",
            STAGE_CACHE_ENV: "0",
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
    snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_dir=MODEL_DIR)
    cache_dir = f"{HF_HOME}/hub"
    for repo, revision in (
        (DINO_ID, DINO_REVISION),
        (MOGE_ID, MOGE_REVISION),
    ):
        snapshot_download(repo, revision=revision, cache_dir=cache_dir)

    pinned_hf_snapshot(
        cache_dir,
        DINO_ID,
        DINO_REVISION,
        required_files=("config.json", "model.safetensors"),
    )
    pinned_hf_snapshot(
        cache_dir,
        MOGE_ID,
        MOGE_REVISION,
        required_files=("model.pt",),
    )

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


def _camera_params_wild_moge_image(
    image,
    moge_model,
    *,
    device: str = "cuda",
    mesh_scale: float = 1.0,
    extend_pixel: int = 0,
    image_resolution: int = 512,
) -> dict:
    """In-memory equivalent of Pixal3D's pinned path-based MoGe helper."""
    import math

    import torch
    from inference import distance_from_fov

    pil_image = image.convert("RGB")
    width, _height = pil_image.size
    image_np = _moge_rgb_float32(pil_image)
    image_tensor = torch.from_numpy(image_np).permute(2, 0, 1).to(device)
    with torch.no_grad():
        output = moge_model.infer(image_tensor)
    intrinsics = output["intrinsics"].squeeze().cpu().numpy()
    fx_normalized = intrinsics[0, 0]
    fx = fx_normalized * width
    camera_angle_x = 2 * math.atan(width / (2 * fx))

    distance = distance_from_fov(
        camera_angle_x,
        torch.tensor([-1.0, 0.0, 0.0]),
        torch.tensor([0 - extend_pixel, image_resolution - 1 + extend_pixel]),
        mesh_scale,
        image_resolution,
    )["distance_from_x"]
    return {
        "camera_angle_x": camera_angle_x,
        "distance": distance,
        "mesh_scale": mesh_scale,
    }


def _moge_rgb_float32(image):
    """Return the exact float32 RGB array consumed by pinned Pixal MoGe."""
    import numpy as np

    return np.array(image.convert("RGB")).astype(np.float32) / 255.0


@app.function(timeout=60)
def worker_info() -> dict:
    return worker_identity(CAPABILITY)


@app.cls(
    image=runtime_image,
    gpu=GPU,
    volumes={"/models": weights, "/artifacts": artifacts, "/pixal-cache": autotune_cache},
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
        from unittest.mock import patch

        sys.path.insert(0, SRC)
        os.chdir(SRC)
        shadow = sys.modules.get("pixal3d")
        if shadow is not None and not hasattr(shadow, "__path__"):
            del sys.modules["pixal3d"]
        import torch
        from inference import IMAGE_COND_CONFIGS, build_image_cond_model, load_moge_model
        from pixal3d.pipelines import Pixal3DImageTo3DPipeline, rembg
        from pixal3d.trainers.flow_matching.mixins import image_conditioned_proj

        class _NoopRemBg:
            def __init__(self, **_):
                pass

            def to(self, _device):
                return self

            cuda = cpu = to

            def __call__(self, _image):
                raise RuntimeError("Pixal3D worker requires a pre-matted RGBA input")

        rembg.BiRefNet = _NoopRemBg
        cache_dir = f"{HF_HOME}/hub"
        dino_dir = pinned_hf_snapshot(
            cache_dir,
            DINO_ID,
            DINO_REVISION,
            required_files=("config.json", "model.safetensors"),
        )
        moge_dir = pinned_hf_snapshot(
            cache_dir,
            MOGE_ID,
            MOGE_REVISION,
            required_files=("model.pt",),
        )
        image_cond_configs = {
            name: {**config, "model_name": str(dino_dir)}
            for name, config in IMAGE_COND_CONFIGS.items()
        }

        Path(FLEX_GEMM_CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)

        def cache_signature():
            cache = Path(FLEX_GEMM_CACHE_PATH)
            if not cache.is_file():
                return None
            stat = cache.stat()
            return (stat.st_size, stat.st_mtime_ns)

        t0 = time.perf_counter()
        self.pipe = Pixal3DImageTo3DPipeline.from_pretrained(MODEL_DIR)
        model_names = {config["model_name"] for config in image_cond_configs.values()}
        if len(model_names) != 1:
            raise RuntimeError(f"Pixal3D image conditioners no longer share one DINO: {model_names}")

        # All four extractors use the exact same frozen DINOv3 checkpoint. Build
        # it once, then let the remaining extractor constructors reuse that same
        # nn.Module. Their ProjGrid/image-size/NAF settings remain independent.
        self.pipe.image_cond_model_ss = build_image_cond_model(image_cond_configs["ss"])
        shared_dino = self.pipe.image_cond_model_ss.model
        with patch.object(
            image_conditioned_proj.DINOv3ViTModel,
            "from_pretrained",
            return_value=shared_dino,
        ):
            self.pipe.image_cond_model_shape_512 = build_image_cond_model(
                image_cond_configs["shape_512"]
            )
            self.pipe.image_cond_model_shape_1024 = build_image_cond_model(
                image_cond_configs["shape_1024"]
            )
            self.pipe.image_cond_model_tex_1024 = build_image_cond_model(
                image_cond_configs["tex_1024"]
            )

        image_cond_names = (
            "image_cond_model_ss",
            "image_cond_model_shape_512",
            "image_cond_model_shape_1024",
            "image_cond_model_tex_1024",
        )
        if any(getattr(self.pipe, name).model is not shared_dino for name in image_cond_names):
            raise RuntimeError("Pixal3D DINO sharing invariant failed")

        self.pipe.low_vram = False
        self.pipe.cuda()
        image_cond_models = [getattr(self.pipe, name).cuda() for name in image_cond_names]

        # The three NAF-enabled branches also use the same frozen NAF weights;
        # only target resolution / ProjGrid differ and stay on each extractor.
        naf_models = [model for model in image_cond_models if model.use_naf_upsample]
        if not naf_models:
            raise RuntimeError("Pixal3D expected NAF-enabled conditioners")
        naf_models[0]._load_naf()
        shared_naf = naf_models[0].naf_model
        for model in naf_models[1:]:
            model.naf_model = shared_naf
        if any(model.naf_model is not shared_naf for model in naf_models):
            raise RuntimeError("Pixal3D NAF sharing invariant failed")

        self.image_cond_backbone_instances = len({id(model.model) for model in image_cond_models})
        self.naf_backbone_instances = len({id(model.naf_model) for model in naf_models})
        self.keep_moge_on_gpu = os.environ.get("PIXAL3D_KEEP_MOGE_ON_GPU", "0") == "1"
        self.moge = load_moge_model(
            device="cuda" if self.keep_moge_on_gpu else "cpu",
            model_name=str(moge_dir / "model.pt"),
        )
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - t0
        self.flex_cache_signature = cache_signature()

    @modal.method()
    def warmup(self) -> dict:
        return {
            "model": CAPABILITY["id"],
            "load_s": self.load_s,
            "image_cond_backbone_instances": self.image_cond_backbone_instances,
            "naf_backbone_instances": self.naf_backbone_instances,
            "attention_backend": os.environ.get("ATTN_BACKEND"),
            "flex_gemm_cache": FLEX_GEMM_CACHE_PATH,
            "moge_resident_gpu": self.keep_moge_on_gpu,
            "stage_empty_cache_suppressed": os.environ.get(STAGE_CACHE_ENV, "0") == "1",
        }

    def _commit_flex_cache_if_changed(self) -> float:
        cache = Path(FLEX_GEMM_CACHE_PATH)
        if not cache.is_file():
            return 0.0
        stat = cache.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        if signature == self.flex_cache_signature:
            return 0.0
        t0 = time.perf_counter()
        autotune_cache.commit()
        self.flex_cache_signature = signature
        return time.perf_counter() - t0

    def _generate(
        self,
        image_bytes: bytes,
        seed: int = 42,
        fov: float | None = None,
        pipeline_type: str = "1536_cascade",
        max_num_tokens: int = 49152,
        texture_size: int = 4096,
    ) -> dict:
        import numpy as np
        import o_voxel
        import torch
        from inference import distance_from_fov
        from PIL import Image

        if pipeline_type not in {"1024_cascade", "1536_cascade"}:
            raise ValueError("pipeline_type must be 1024_cascade or 1536_cascade")
        if not 32768 <= max_num_tokens <= 65536:
            raise ValueError("max_num_tokens must be between 32768 and 65536")
        if texture_size not in {2048, 4096}:
            raise ValueError("texture_size must be 2048 or 4096")
        profiler = GpuStageProfiler(torch).start()
        worker_t0 = time.perf_counter()
        try:
            with profiler.stage("preprocess", cuda_sync=False):
                image = Image.open(io.BytesIO(image_bytes))
                image = self.pipe.preprocess_image(image)

            with tempfile.TemporaryDirectory(prefix="pixal3d-") as temp_dir:
                work = Path(temp_dir)
                with profiler.stage("camera"):
                    if fov is None:
                        if not self.keep_moge_on_gpu:
                            self.moge.cuda()
                        camera = _camera_params_wild_moge_image(image, self.moge, device="cuda")
                        if not self.keep_moge_on_gpu:
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
                        camera = {
                            "camera_angle_x": fov,
                            "distance": distance,
                            "mesh_scale": 1.0,
                        }

                with profiler.stage("pipeline"):
                    meshes, (_, _, resolution) = self.pipe.run(
                        image,
                        camera_params=camera,
                        seed=seed,
                        preprocess_image=False,
                        return_latent=True,
                        pipeline_type=pipeline_type,
                        max_num_tokens=max_num_tokens,
                    )

                with profiler.stage("flex_cache_commit", cuda_sync=False):
                    flex_cache_commit_s = self._commit_flex_cache_if_changed()

                mesh = meshes[0]
                with profiler.stage("o_voxel_validate"):
                    o_voxel_intermediate = validate_o_voxel_pbr_intermediate(
                        vertices=mesh.vertices,
                        faces=mesh.faces,
                        attrs=mesh.attrs,
                        coords=mesh.coords,
                        attr_layout=self.pipe.pbr_attr_layout,
                        grid_size=int(resolution),
                    )

                with profiler.stage("glb_postprocess"):
                    glb = o_voxel.postprocess.to_glb(
                        vertices=mesh.vertices,
                        faces=mesh.faces,
                        attr_volume=mesh.attrs,
                        coords=mesh.coords,
                        attr_layout=self.pipe.pbr_attr_layout,
                        grid_size=resolution,
                        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
                        decimation_target=1_000_000,
                        texture_size=texture_size,
                        remesh=True,
                        remesh_band=1,
                        remesh_project=0,
                        use_tqdm=False,
                    )

                with profiler.stage("transform"):
                    glb.apply_transform(
                        np.array(
                            [
                                [-1, 0, 0, 0],
                                [0, 0, -1, 0],
                                [0, -1, 0, 0],
                                [0, 0, 0, 1],
                            ],
                            dtype=np.float64,
                        )
                    )

                output_path = work / "output.glb"
                with profiler.stage("glb_export"):
                    glb.export(output_path, extension_webp=True)

                with profiler.stage("artifact_write", cuda_sync=False):
                    name = f"pixal3d/{uuid.uuid4().hex}.glb"
                    dst = Path("/artifacts") / name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(output_path, dst)
        finally:
            profiler.timings["worker_total_s"] = time.perf_counter() - worker_t0
            gpu_telemetry = profiler.stop()

        generation_s = profiler.timings["pipeline_s"]
        postprocess_s = sum(
            profiler.timings[key]
            for key in ("glb_postprocess_s", "transform_s", "glb_export_s")
        )
        inference_s = generation_s + postprocess_s
        profiler.timings.update(
            {
                "input_save_s": 0.0,
                "generation_s": generation_s,
                "to_glb_s": profiler.timings["glb_postprocess_s"],
                "total_s": profiler.timings["worker_total_s"],
            }
        )
        return {
            "model": "pixal3d",
            "gpu": GPU,
            "resolution": int(resolution),
            "pipeline_type": pipeline_type,
            "max_num_tokens": max_num_tokens,
            "texture_size": texture_size,
            "fov": fov,
            "seed": seed,
            "artifact": name,
            "glb_bytes": dst.stat().st_size,
            "source_vertices": len(mesh.vertices),
            "source_faces": len(mesh.faces),
            "load_s": self.load_s,
            "inference_s": inference_s,
            "generation_s": generation_s,
            "postprocess_s": postprocess_s,
            "o_voxel_intermediate": o_voxel_intermediate,
            "peak_vram_gb": gpu_telemetry.get("peak_vram_gb"),
            "attention_backend": os.environ.get("ATTN_BACKEND"),
            "moge_resident_gpu": self.keep_moge_on_gpu,
            "stage_empty_cache_suppressed": os.environ.get(STAGE_CACHE_ENV, "0") == "1",
            "flex_gemm_cache_path": FLEX_GEMM_CACHE_PATH,
            "flex_cache_commit_s": flex_cache_commit_s,
            "timings": profiler.timings,
            "gpu_telemetry": gpu_telemetry,
        }

    @modal.method()
    def generate_job(self, input_path: str, options: dict | None = None) -> dict:
        """Direct GPU entrypoint: the local client spawns this method.

        Input reading, canonical validation, GLB validation and result
        normalization all happen here so no CPU adapter function is needed.
        """
        return run_generation_job(
            CAPABILITY["id"],
            artifacts,
            self._generate,
            input_path,
            options,
            quality_profile="pbr_textured",
        )
