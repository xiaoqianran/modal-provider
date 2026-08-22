from __future__ import annotations

import io
import time
import uuid
from pathlib import Path

import modal

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

SRC = Path("/opt/fastsam3d-plus-plus")
MODEL_DIR = Path("/models/sam3d")
PIPELINE = MODEL_DIR / "checkpoints/pipeline.fast.yaml"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-fastsam3d-weights", create_if_missing=True)
artifacts = modal.Volume.from_name("modal-3d-artifacts", create_if_missing=True)


def _patch_sources() -> None:
    from pathlib import Path

    root = Path("/opt/fastsam3d-plus-plus")

    # The SAM checkpoints strictly reload the full condition embedder, so avoid a redundant
    # network fetch of DINO weights during model construction.
    p = root / "sam3d_objects/model/backbone/dit/embedder/dino.py"
    s = p.read_text()
    old = "                verbose=False,\n                **backbone_kwargs,"
    new = "                verbose=False,\n                pretrained=False,\n                **backbone_kwargs,"
    if old not in s:
        raise RuntimeError("DINO patch target changed")
    p.write_text(s.replace(old, new, 1))

    # Production uses ordinary checkpoint files; avoid Lightning, which is only needed
    # for sharded training checkpoints and LightningModule-specific hooks.
    p = root / "sam3d_objects/model/io.py"
    s = p.read_text()
    s = s.replace("import lightning.pytorch as pl\n", "", 1)
    lightning_start = "from lightning.pytorch.utilities.consolidate_checkpoint import (\n"
    lightning_end = ")\nfrom glob import glob\n"
    if lightning_start not in s or lightning_end not in s:
        raise RuntimeError("Lightning checkpoint patch target changed")
    before, rest = s.split(lightning_start, 1)
    _, after = rest.split(lightning_end, 1)
    s = before + "from glob import glob\n" + after
    s = s.replace("model: Union[pl.LightningModule, torch.nn.Module]", "model: torch.nn.Module", 1)
    s = s.replace(
        "    if isinstance(model, pl.LightningModule):\n        model.on_load_checkpoint(checkpoint)\n\n",
        "    if hasattr(model, 'on_load_checkpoint'):\n        model.on_load_checkpoint(checkpoint)\n\n",
        1,
    )
    start = s.index("def load_sharded_checkpoint(")
    end = s.index("\ndef load_model_from_checkpoint(", start)
    replacement = (
        "def load_sharded_checkpoint(path: str, device):\n"
        "    raise RuntimeError(\"sharded Lightning checkpoints are not supported in inference\")\n\n"
    )
    s = s[:start] + replacement + s[end + 1:]
    p.write_text(s)

    # Kaolin is otherwise used here only for a shape assertion helper.
    p = root / "sam3d_objects/model/backbone/tdfy_dit/representations/mesh/flexicubes/flexicubes.py"
    s = p.read_text()
    old = "from kaolin.utils.testing import check_tensor\n"
    new = '''def check_tensor(x, shape, throw=True):\n    ok = x.ndim == len(shape) and all(expected is None or x.shape[i] == expected for i, expected in enumerate(shape))\n    if throw and not ok:\n        raise ValueError(f"unexpected tensor shape {tuple(x.shape)}; expected {shape}")\n    return ok\n'''
    if old not in s:
        raise RuntimeError("Kaolin patch target changed")
    p.write_text(s.replace(old, new, 1))

    # Fast-SAM3D only needs the numeric 3D HFER on the production path, not HTML plots.
    p = root / "sam3d_objects/pipeline/inference_pipeline.py"
    s = p.read_text()
    old = 'process_and_visualize(coords_value, output_dir="./visualization", filter_radius=8 , draw_spatial = True, draw_freq = False)'
    new = 'process_and_visualize(coords_value, output_dir="./visualization", filter_radius=8, draw_spatial=False, draw_freq=False)'
    if old not in s:
        raise RuntimeError("HFER patch target changed")
    p.write_text(s.replace(old, new, 1))

    p = root / "fft/fft3d.py"
    s = p.read_text()
    if "import plotly.graph_objects as go\n" not in s:
        raise RuntimeError("Plotly patch target changed")
    p.write_text(s.replace("import plotly.graph_objects as go\n", "", 1))

    # Plane estimation is not part of single-object generation; keep it lazy instead of
    # making Open3D a mandatory import for the entire pipeline.
    p = root / "sam3d_objects/pipeline/inference_utils.py"
    s = p.read_text()
    if "import open3d as o3d\n" not in s:
        raise RuntimeError("Open3D patch target changed")
    s = s.replace("import open3d as o3d\n", "", 1)
    layout_start = "from sam3d_objects.pipeline.layout_post_optimization_utils import (\n"
    layout_end = ")\n\n\nSLAT_STD"
    if layout_start not in s or layout_end not in s:
        raise RuntimeError("layout import patch target changed")
    before, rest = s.split(layout_start, 1)
    _, after = rest.split(layout_end, 1)
    s = before + "SLAT_STD" + after
    marker = "    set_seed(100)\n"
    lazy = (
        "    from sam3d_objects.pipeline.layout_post_optimization_utils import (\n"
        "        run_ICP, compute_iou, set_seed, apply_transform, get_mesh,\n"
        "        get_mask_renderer, run_alignment, run_render_compare, check_occlusion,\n"
        "    )\n\n"
        "    set_seed(100)\n"
    )
    if marker not in s:
        raise RuntimeError("layout function patch target changed")
    s = s.replace(marker, lazy, 1)
    s = s.replace("def o3d_plane_estimation(points):\n", "def o3d_plane_estimation(points):\n    import open3d as o3d\n", 1)
    p.write_text(s)

    # Fast-SAM3D ships plotting helpers in the generator module; inference never calls them.
    p = root / "sam3d_objects/model/backbone/generator/shortcut/model.py"
    s = p.read_text()
    header = (
        "import seaborn as sns\n"
        "import plotly.graph_objects as go\n"
        "import matplotlib.pyplot as plt\n\n\n"
        "from sklearn.decomposition import PCA\n"
        "import matplotlib.pyplot as plt\n"
        "import matplotlib.ticker as ticker\n"
    )
    if header not in s:
        raise RuntimeError("shortcut visualization header changed")
    s = s.replace(header, "from sklearn.decomposition import PCA\n", 1)
    p.write_text(s)

    # Avoid importing Matplotlib just to read an image in a helper not used by our ndarray path.
    p = root / "sam3d_objects/data/dataset/tdfy/img_and_mask_transforms.py"
    s = p.read_text()
    if "import matplotlib.pyplot as plt\n" not in s:
        raise RuntimeError("Matplotlib image loader patch target changed")
    s = s.replace("import matplotlib.pyplot as plt\n", "from PIL import Image\n", 1)
    s = s.replace("image = plt.imread(fpath)  # Why use matplotlib?", "image = np.asarray(Image.open(fpath))")
    p.write_text(s)

    # Vertex-color GLB generation does not execute mesh repair, texture baking or Gaussian
    # rendering. Avoid importing those optional stacks on the hot path.
    p = root / "sam3d_objects/model/backbone/tdfy_dit/utils/postprocessing_utils.py"
    s = p.read_text()
    for line in (
        "import xatlas\n",
        "import pyvista as pv\n",
        "from pymeshfix import _meshfix\n",
        "import igraph\n",
        "from .render_utils import render_multiview\n",
        "from ..renderers import GaussianRenderer\n",
    ):
        if line not in s:
            raise RuntimeError(f"postprocess patch target changed: {line.strip()}")
        s = s.replace(line, "", 1)
    p.write_text(s)

    # Importing the pipeline during image build must not assume a GPU exists.
    p = root / "sam3d_objects/pipeline/inference_pipeline.py"
    s = p.read_text()
    old = "def set_attention_backend():\n    if torch.cuda.is_available():"
    new = 'def set_attention_backend():\n    gpu_name = ""\n    if torch.cuda.is_available():'
    if old not in s:
        raise RuntimeError("GPU import patch target changed")
    p.write_text(s.replace(old, new, 1))


download_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .uv_pip_install("huggingface_hub==0.30.2", "hf_xet==1.1.9", uv_version="0.12.5")
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.1.1-devel-ubuntu22.04", add_python="3.11")
    .apt_install("git", "build-essential", "ninja-build", "cmake", "libgl1", "libglib2.0-0", "libgomp1")
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
        f"git clone https://github.com/facebookresearch/pytorch3d.git /opt/pytorch3d && git -C /opt/pytorch3d checkout {PYTORCH3D_COMMIT}",
    )
    .run_commands(
        "cd /opt/pytorch3d && CC=gcc CXX=g++ TORCH_CUDA_ARCH_LIST=8.9 CUDA_HOME=/usr/local/cuda FORCE_CUDA=1 MAX_JOBS=4 python -m pip install --no-build-isolation --no-deps .",
    )
    .run_function(_patch_sources)
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
        local_dir=MODEL_DIR,
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
    snapshot_download(MOGE_REPO, revision=MOGE_REVISION, local_dir="/models/moge", allow_patterns=["model.pt"])

    ckpt = MODEL_DIR / "checkpoints"
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
    PIPELINE.write_text("\n".join(lines) + "\n")

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
    scaledown_window=60,
    timeout=30 * 60,
    startup_timeout=20 * 60,
)
class Model:
    @modal.enter()
    def load(self) -> None:
        import torch
        from hydra.utils import instantiate
        from omegaconf import OmegaConf

        if torch.cuda.get_device_capability() != (8, 9):
            raise RuntimeError(f"expected L40S sm_89, got {torch.cuda.get_device_name()}")

        config = OmegaConf.load(PIPELINE)
        config.workspace_dir = str(PIPELINE.parent)
        config.rendering_engine = "pytorch3d"
        config.compile_model = False

        t0 = time.perf_counter()
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
        self.load_s = time.perf_counter() - t0

    @modal.method()
    def generate(
        self,
        image_bytes: bytes,
        seed: int = 42,
        dmd_interval: int = 1,
        dmd_history: int = 5,
    ) -> dict:
        import cv2
        import numpy as np
        import torch
        from PIL import Image
        from fft.fft2d import calculate_hfer_robust

        image = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGBA"), dtype=np.uint8)
        alpha = image[..., 3]
        if alpha.min() == 255:
            raise ValueError("FastSAM3D++ input must contain a foreground alpha mask")

        # Fast-SAM3D's spectral mesh policy uses the object crop HFER.
        tmp = Path("/tmp/fastsam3d-input.png")
        cv2.imwrite(str(tmp), cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA))
        self.pipe.hfer_2d = float(calculate_hfer_robust(str(tmp)))

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
        glb = out["glb"].export(file_type="glb")
        name = f"fastsam3d-plus-plus/{uuid.uuid4().hex}.glb"
        path = Path("/artifacts") / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(glb)
        artifacts.commit()

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
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "load_s": self.load_s,
            "inference_s": inference_s,
            "peak_vram_allocated_gb": torch.cuda.max_memory_allocated() / 2**30,
            "peak_vram_reserved_gb": torch.cuda.max_memory_reserved() / 2**30,
        }


adapter_image = modal.Image.debian_slim(python_version="3.11")


@app.function(image=adapter_image, volumes={"/artifacts": artifacts}, timeout=30 * 60, max_containers=1)
def generate(input_path: str, options: dict | None = None) -> dict:
    rel = Path(input_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("input_path must be relative to /artifacts")
    path = Path("/artifacts") / rel
    if not path.is_file():
        raise FileNotFoundError(input_path)
    return Model().generate.remote(path.read_bytes(), **dict(options or {}))
