from __future__ import annotations

import io
import time
import uuid
from pathlib import Path, PurePosixPath

import modal

from .common import (
    generation_result,
    register_worker_entrypoint,
    validate_canonical_input,
    validate_canonical_png,
    validate_glb,
    worker_capability,
)

APP_NAME = "modal-3d-fastsam3d"
GPU = "L40S"

FORK = "Archerkattri/fastsam3d-plus-plus"
FORK_COMMIT = "36191e491ca0bf9d51cda39aa7b6c91205eb82e3"
SAM_REPO = "facebook/sam-3d-objects"
SAM_REVISION = "2e73555018d2741ccd486e56c24fac41155a1dc6"
MOGE_REPO = "Ruicheng/moge-vitl"
MOGE_REVISION = "ad326bfb61facd6c52b5a825bc1e34d7c97d9672"
MOGE_COMMIT = "a8c37341bc0325ca99b9d57981cc3bb2bd3e255b"
UTILS3D_COMMIT = "3913c65d81e05e47b9f367250cf8c0f7462a0900"
DINO_COMMIT = "7764ea0f912e53c92e82eb78a2a1631e92725fc8"
PYTORCH3D_COMMIT = "75ebeeaea0908c5527e7b1e305fbc7681382db47"
BUILD_TAG = "fastsam3d-pytorch3d-py311-cu121-torch251-sm89-v1"
PYTORCH3D_WHEELS_URL = (
    f"https://github.com/xiaoqianran/modal-build/releases/download/{BUILD_TAG}/{BUILD_TAG}.wheels.zip"
)

# These paths are interpreted by Linux image-build/runtime code. PurePosixPath
# keeps their spelling stable when the deployment command itself runs on Windows.
SRC = PurePosixPath("/opt/fastsam3d-plus-plus")
MODEL_DIR = PurePosixPath("/models/sam3d")
PIPELINE = MODEL_DIR / "checkpoints/pipeline.fast.yaml"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-fastsam3d-weights", create_if_missing=True)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)

CAPABILITY = worker_capability(
    "fastsam3d-plus-plus",
    "FastSAM3D++",
    APP_NAME,
    "最快的彩色资产生成；vertex-color GLB",
    {
        "seed": {"type": "integer", "default": 42, "minimum": 0, "maximum": 4294967295},
        "dmd_interval": {"type": "integer", "default": 1, "minimum": 1, "maximum": 12},
        "dmd_history": {"type": "integer", "default": 5, "minimum": 4, "maximum": 25},
    },
    profile={"dmd_interval": 1, "dmd_history": 5},
    profile_name="推荐 · Fast-SAM3D 加速",
    profile_metadata={
        "quality": {
            "tier": "accelerated",
            "basis": "wlfeng0509/Fast-SAM3D official acceleration recipe",
            "sampler": {
                "runtime_ss_steps": 25,
                "runtime_slat_steps": 25,
                "generator_config_ss_steps": 2,
                "generator_config_slat_steps": 12,
                "ss_cache_stride": 3,
                "slat_carving_ratio": 0.1,
            },
            "verification": {
                "status": "verified",
                "benchmark": "benchmarks/full-quality-smoke-2026-08-28.json",
            },
        }
    },
    reference_metadata={
        "status": "legacy",
        "benchmark": "benchmarks/fastsam3d-plus-plus-l40s-2026-08-23.json",
        "metric": "adapter_wall_s",
        "profile_id": "recommended",
    },
    output="textured",
    deployment={
        "source": FORK,
        "source_revision": FORK_COMMIT,
        "sam_revision": SAM_REVISION,
        "pytorch3d_revision": PYTORCH3D_COMMIT,
        "build_artifact": BUILD_TAG,
    },
    warm_seconds=6.06,
    cold_start_seconds=60.0,
    generation_entrypoint={
        "kind": "class_method",
        "class_name": "Model",
        "method_name": "generate_job",
    },
    priority=10,
)


PATCH = Path(__file__).parent / "patches/fastsam3d.patch"
download_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .uv_pip_install("huggingface_hub==0.30.2", "hf_xet==1.1.9", uv_version="0.12.5")
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.1.1-devel-ubuntu22.04", add_python="3.11")
    .apt_install(
        "git", "curl", "unzip", "libgl1", "libglib2.0-0", "libgomp1"
    )
    .uv_pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        index_url="https://download.pytorch.org/whl/cu121",
        uv_version="0.12.5",
    )
    .uv_pip_install(
        "wheel==0.44.0",
        "astor==0.8.1",
        "plyfile==1.1",
        "huggingface_hub==0.30.2",
        "numpy==1.26.4",
        "opencv-python-headless==4.9.0.80",
        "scipy==1.14.1",
        "hydra-core==1.3.2",
        "omegaconf==2.3.0",
        "loguru==0.7.2",
        "easydict==1.13",
        "einops==0.8.0",
        "einops-exts==0.0.4",
        "optree==0.14.1",
        "roma==1.5.1",
        "trimesh==4.5.1",
        "Pillow==10.4.0",
        "tqdm==4.66.5",
        "safetensors==0.4.4",
        "fvcore==0.1.5.post20221221",
        "iopath==0.1.10",
        "scikit-learn==1.5.2",
        "timm==0.9.16",
        "spconv-cu121==2.3.8",
        uv_version="0.12.5",
    )
    .run_commands(
        f"git clone https://github.com/{FORK}.git {SRC} && git -C {SRC} checkout {FORK_COMMIT}",
        f"git clone https://github.com/microsoft/MoGe.git /opt/MoGe && git -C /opt/MoGe checkout {MOGE_COMMIT}",
        f"git clone https://github.com/EasternJournalist/utils3d.git /opt/utils3d && git -C /opt/utils3d checkout {UTILS3D_COMMIT}",
        f"git clone https://github.com/facebookresearch/dinov2.git /root/.cache/torch/hub/facebookresearch_dinov2_main && git -C /root/.cache/torch/hub/facebookresearch_dinov2_main checkout {DINO_COMMIT}",
    )
    .add_local_file(PATCH, "/tmp/fastsam3d.patch", copy=True)
    .run_commands(
        # Windows Git checkouts may materialize .patch files with CRLF. Normalize
        # inside the Linux image before matching patch context.
        "python -c \"from pathlib import Path; p=Path('/tmp/fastsam3d.patch'); p.write_bytes(p.read_bytes().replace(bytes((13, 10)), bytes((10,))))\"",
        f"git -C {SRC} apply --check /tmp/fastsam3d.patch && git -C {SRC} apply /tmp/fastsam3d.patch",
    )
    .run_commands(
        f"curl -fL '{PYTORCH3D_WHEELS_URL}' -o /tmp/pytorch3d-wheels.zip && "
        "mkdir -p /tmp/pytorch3d-wheels && unzip -q /tmp/pytorch3d-wheels.zip -d /tmp/pytorch3d-wheels && "
        "uv pip install --system --no-deps /tmp/pytorch3d-wheels/*.whl",
        'python -c "import torch, pytorch3d; from pytorch3d.renderer import MeshRasterizer; '
        "assert torch.__version__.startswith('2.5.1'); print(pytorch3d.__file__, MeshRasterizer)\"",
    )
    .run_commands(
        f"python {SRC}/patching/hydra",
        f"python -m py_compile {SRC}/sam3d_objects/model/backbone/generator/shortcut/model.py {SRC}/fft/fft3d.py {SRC}/sam3d_objects/pipeline/inference_utils.py {SRC}/sam3d_objects/model/io.py",
        f"PYTHONPATH={SRC}:/opt/MoGe:/opt/utils3d python -c \"from sam3d_objects.pipeline.inference_pipeline_pointmap import InferencePipelinePointMap; print('fastsam3d import ok')\"",
    )
    .env(
        {
            "PYTHONPATH": f"{SRC}:/opt/MoGe:/opt/utils3d",
            "TORCH_HOME": "/models/torch",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "ATTN_BACKEND": "sdpa",
            "SPARSE_ATTN_BACKEND": "sdpa",
            "SPARSE_BACKEND": "spconv",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            "PYTHONUNBUFFERED": "1",
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
        SAM_REPO,
        revision=SAM_REVISION,
        local_dir=str(MODEL_DIR),
        allow_patterns=[
            "checkpoints/pipeline.yaml",
            "checkpoints/ss_generator.yaml",
            "checkpoints/ss_generator.ckpt",
            "checkpoints/slat_generator.yaml",
            "checkpoints/slat_generator.ckpt",
            "checkpoints/ss_decoder.yaml",
            "checkpoints/ss_decoder.ckpt",
            "checkpoints/slat_decoder_mesh.yaml",
            "checkpoints/slat_decoder_mesh.ckpt",
            "checkpoints/slat_decoder_gs.yaml",
            "checkpoints/slat_decoder_gs.ckpt",
            "checkpoints/slat_decoder_gs_4.yaml",
            "checkpoints/slat_decoder_gs_4.ckpt",
        ],
    )
    snapshot_download(
        MOGE_REPO, revision=MOGE_REVISION, local_dir="/models/moge", allow_patterns=["model.pt"]
    )

    ckpt = Path(MODEL_DIR) / "checkpoints"
    ss = (ckpt / "ss_generator.yaml").read_text()
    slat = (ckpt / "slat_generator.yaml").read_text()
    (ckpt / "ss_generator_faster.yaml").write_text(
        ss.replace(
            "sam3d_objects.model.backbone.generator.shortcut.model.ShortCut",
            "sam3d_objects.model.backbone.generator.shortcut.model.ShortCut_faster",
            1,
        )
    )
    (ckpt / "slat_generator_faster.yaml").write_text(
        slat.replace(
            "sam3d_objects.model.backbone.generator.flow_matching.model.FlowMatching",
            "sam3d_objects.model.backbone.generator.flow_matching.model.FlowMatching_faster",
            1,
        )
    )
    pipeline = (ckpt / "pipeline.yaml").read_text()
    for old, new in (
        ("ss_generator.yaml", "ss_generator_faster.yaml"),
        ("slat_generator.yaml", "slat_generator_faster.yaml"),
        ("compile_model: true", "compile_model: false"),
        ("slat_decoder_gs_4_config_path: slat_decoder_gs_4.yaml", "slat_decoder_gs_4_config_path: null"),
        ("slat_decoder_gs_4_ckpt_path: slat_decoder_gs_4.ckpt", "slat_decoder_gs_4_ckpt_path: null"),
    ):
        if old not in pipeline:
            raise RuntimeError(f"pipeline config changed: missing {old}")
        pipeline = pipeline.replace(old, new, 1)
    lines = pipeline.splitlines()
    hits = [i for i, line in enumerate(lines) if "pretrained_model_name_or_path:" in line]
    if len(hits) != 1:
        raise RuntimeError(f"expected one MoGe model path, found {len(hits)}")
    i = hits[0]
    indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
    lines[i] = f"{indent}pretrained_model_name_or_path: /models/moge/model.pt"
    Path(PIPELINE).write_text("\n".join(lines) + "\n")

    weights.commit()
    total = sum(p.stat().st_size for p in Path("/models").rglob("*") if p.is_file())
    return {
        "bytes": total,
        "elapsed_s": time.perf_counter() - t0,
        "sam_revision": SAM_REVISION,
        "moge_revision": MOGE_REVISION,
    }


@app.cls(
    image=runtime_image,
    gpu=GPU,
    volumes={"/models": weights, "/artifacts": artifacts},
    min_containers=0,
    max_containers=1,
    scaledown_window=120,
    timeout=30 * 60,
    startup_timeout=20 * 60,
)
class Model:
    @modal.enter()
    def load(self) -> None:
        startup_t0 = time.perf_counter()

        imports_t0 = time.perf_counter()
        import torch
        from hydra.utils import instantiate
        from omegaconf import OmegaConf
        imports_s = time.perf_counter() - imports_t0

        cuda_check_t0 = time.perf_counter()
        if torch.cuda.get_device_capability() != (8, 9):
            raise RuntimeError(f"expected L40S sm_89, got {torch.cuda.get_device_name()}")
        cuda_check_s = time.perf_counter() - cuda_check_t0

        config_t0 = time.perf_counter()
        # OmegaConf only accepts concrete pathlib.Path/str/file handles; keep
        # PIPELINE as PurePosixPath for Windows-safe deployment, but cross the
        # third-party API boundary as a plain POSIX string inside Linux.
        config = OmegaConf.load(str(PIPELINE))
        config.workspace_dir = str(PIPELINE.parent)
        config.rendering_engine = "pytorch3d"
        config.compile_model = False
        config_s = time.perf_counter() - config_t0

        load_t0 = time.perf_counter()
        self.pipe = instantiate(config)
        self.pipe.ss_params = {
            "ss_faster_stride": 3,
            "ss_warmup": 2,
            "ss_order": 1,
            "ss_momentum_beta": 0.5,
        }
        self.pipe.slat_params = {
            "slat_thresh": 1.5,
            "slat_warmup": 3,
            "slat_token_ratio": 0.1,
        }
        self.pipe.mesh_params = {
            "mesh_spectral_threshold_low": 0.5,
            "mesh_spectral_threshold_high": 0.7,
        }
        self.pipe.enable_mesh = True
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - load_t0
        self.startup_s = time.perf_counter() - startup_t0
        self.load_profile = {
            "imports_s": imports_s,
            "cuda_check_s": cuda_check_s,
            "config_s": config_s,
            "model_load_s": self.load_s,
            "total_s": self.startup_s,
        }
        print(f"FASTSAM3D_STARTUP_PROFILE {self.load_profile}", flush=True)

    @modal.method()
    def warmup(self) -> dict:
        return {
            "model": CAPABILITY["id"],
            "load_s": self.load_s,
            "startup_s": self.startup_s,
            "load_profile": self.load_profile,
        }

    def _generate(
        self,
        image_bytes: bytes,
        seed: int = 42,
        dmd_interval: int = 1,
        dmd_history: int = 5,
    ) -> dict:
        import cv2
        import numpy as np
        import torch
        from fft.fft2d import calculate_hfer_robust
        from PIL import Image

        if not 0 <= seed <= 4294967295:
            raise ValueError("seed must be between 0 and 4294967295")
        if not 1 <= dmd_interval <= 12:
            raise ValueError("dmd_interval must be between 1 and 12")
        if not 4 <= dmd_history <= 25:
            raise ValueError("dmd_history must be between 4 and 25")

        wall_t0 = time.perf_counter()
        decode_t0 = time.perf_counter()
        image = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGBA"), dtype=np.uint8)
        decode_s = time.perf_counter() - decode_t0
        alpha = image[..., 3]
        if alpha.min() == 255:
            raise ValueError("FastSAM3D++ input must contain a foreground alpha mask")

        # Fast-SAM3D's spectral mesh policy uses the object crop HFER.
        hfer_t0 = time.perf_counter()
        tmp = Path("/tmp/fastsam3d-input.png")
        cv2.imwrite(str(tmp), cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA))
        self.pipe.hfer_2d = float(calculate_hfer_robust(str(tmp)))
        hfer_s = time.perf_counter() - hfer_t0

        fm = self.pipe.models["slat_generator"]
        if dmd_interval <= 1:
            fm.disable_hicache()
        else:
            fm.enable_dmd(
                interval=dmd_interval,
                first_enhance=2,
                end_enhance=None,
                history=dmd_history,
                max_order=2,
                sigma=0.5,
            )

        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        out = self.pipe.run(
            image,
            None,
            seed,
            stage1_only=False,
            with_mesh_postprocess=False,
            with_texture_baking=False,
            with_layout_postprocess=False,
            use_vertex_color=True,
        )
        torch.cuda.synchronize()
        inference_s = time.perf_counter() - t0

        mesh = out["mesh"][0]
        export_t0 = time.perf_counter()
        glb = out["glb"].export(file_type="glb")
        export_s = time.perf_counter() - export_t0

        artifact_t0 = time.perf_counter()
        name = f"fastsam3d-plus-plus/{uuid.uuid4().hex}.glb"
        path = Path("/artifacts") / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(glb)
        artifacts.commit()
        artifact_s = time.perf_counter() - artifact_t0
        total_s = time.perf_counter() - wall_t0

        return {
            "model": "fastsam3d-plus-plus",
            "fork_commit": FORK_COMMIT,
            "sam_revision": SAM_REVISION,
            "moge_revision": MOGE_REVISION,
            "gpu": torch.cuda.get_device_name(),
            "seed": seed,
            "dmd_interval": dmd_interval,
            "dmd_enabled": dmd_interval > 1,
            "dmd_history": dmd_history,
            "hfer_2d": self.pipe.hfer_2d,
            "artifact": name,
            "glb_bytes": len(glb),
            "source_vertices": len(mesh.vertices),
            "source_faces": len(mesh.faces),
            "load_s": self.load_s,
            "startup_s": self.startup_s,
            "load_profile": self.load_profile,
            "inference_s": inference_s,
            "timings": {
                "decode_s": decode_s,
                "hfer_s": hfer_s,
                "inference_s": inference_s,
                "glb_export_s": export_s,
                "artifact_write_commit_s": artifact_s,
                "total_s": total_s,
            },
            "peak_vram_allocated_gb": torch.cuda.max_memory_allocated() / 2**30,
            "peak_vram_reserved_gb": torch.cuda.max_memory_reserved() / 2**30,
        }

    @modal.method()
    def generate(
        self,
        image_bytes: bytes,
        seed: int = 42,
        dmd_interval: int = 1,
        dmd_history: int = 5,
    ) -> dict:
        return self._generate(
            image_bytes,
            seed=seed,
            dmd_interval=dmd_interval,
            dmd_history=dmd_history,
        )

    @modal.method()
    def generate_job(self, input_path: str, options: dict | None = None) -> dict:
        job_t0 = time.perf_counter()
        rel = Path(input_path)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] != "client-inputs":
            raise ValueError("input_path must be under client-inputs/ and relative to /artifacts")

        input_path_obj = Path("/artifacts") / rel
        if not input_path_obj.is_file():
            artifacts.reload()
        if not input_path_obj.is_file():
            raise FileNotFoundError(input_path)

        input_t0 = time.perf_counter()
        validate_canonical_input(input_path_obj, input_path)
        image_bytes = input_path_obj.read_bytes()
        input_validation_s = time.perf_counter() - input_t0

        value = self._generate(image_bytes, **dict(options or {}))
        artifact_rel = Path(str(value.get("artifact", "")))
        if not artifact_rel.parts or artifact_rel.is_absolute() or ".." in artifact_rel.parts:
            raise ValueError("worker artifact path must be relative to /artifacts")
        expected_size = value.get("glb_bytes")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size <= 0:
            raise ValueError("worker result must contain a positive glb_bytes integer")

        artifact_t0 = time.perf_counter()
        metadata = validate_glb(Path("/artifacts") / artifact_rel, expected_size)
        artifact_validation_s = time.perf_counter() - artifact_t0
        metadata["path"] = artifact_rel.as_posix()
        timings = value.setdefault("timings", {})
        timings["job_input_validation_s"] = input_validation_s
        timings["job_artifact_validation_s"] = artifact_validation_s
        timings["job_total_s"] = time.perf_counter() - job_t0
        return generation_result(CAPABILITY["id"], value, metadata)


generate, warmup, register = register_worker_entrypoint(app, artifacts, Model, CAPABILITY)
