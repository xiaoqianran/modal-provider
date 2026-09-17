"""FIRE3D image; independent of HYWorld2 workers and model dependencies."""

from __future__ import annotations

import modal

FIRE3D_REVISION = "2368dd2f3909120cf90bbf8a17807abe9c41e600"
FIRE3D_SOURCE = "/opt/Fire3D"
FIRE3D_GPU = "H100"
FIRE3D_PYTHON = "3.10"
FIRE3D_CUDA = "12.8.1"
FIRE3D_TORCH = "2.7.1"
FIRE3D_TORCHVISION = "0.22.1"
FIRE3D_TORCHAUDIO = "2.7.1"
FIRE3D_SINGLE_IMAGE_SCENE = "003025"
FIRE3D_BUILD_ARTIFACT_VOLUME = "modal-build-artifacts"
FIRE3D_BUILD_ARTIFACT_MOUNT = "/build-artifacts"
FIRE3D_RUNTIME_CACHE_VOLUME = "fire3d-runtime-cache-v1"
FIRE3D_RUNTIME_CACHE_MOUNT = "/runtime-cache"
FIRE3D_FLASH_ATTN_TAG = "fire3d-flash-attn-py310-cu128-torch271-sm90-v1"
FIRE3D_FLASH_ATTN_VERSION = "2.7.3"
FIRE3D_PYTORCH3D_TAG = "fire3d-pytorch3d-py310-cu128-torch271-sm90-v1"
FIRE3D_PYTORCH3D_VERSION = "0.7.8"
PI3_SOURCE = "/opt/Pi3"
PI3_SOURCE_REVISION = "9fa3ddb3f8d53041f8b2738df404f62223bbaa7b"

# The official installer compiles several CUDA extensions. Building from the CUDA
# devel image supplies nvcc; targeting sm90 keeps the first reproduction path close
# to the published 80 GB A100 / large-memory release environment while using a GPU
# type already supported by this monorepo. Blackwell is a separate optimization gate.
fire3d_image = (
    modal.Image.from_registry(
        f"nvidia/cuda:{FIRE3D_CUDA}-devel-ubuntu22.04", add_python=FIRE3D_PYTHON
    )
    .apt_install(
        "build-essential",
        "clang",
        "cmake",
        "curl",
        "ffmpeg",
        "git",
        "git-lfs",
        "libgl1",
        "libglib2.0-0",
        "ninja-build",
    )
    .env(
        {
            "CC": "gcc",
            "CXX": "g++",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_CACHE_DIR": "1",
            "MAX_JOBS": "4",
            "TORCH_CUDA_ARCH_LIST": "9.0",
        }
    )
    .run_commands(
        "python -m pip install --upgrade pip setuptools wheel 'cmake>=3.28'",
        f"python -m pip install torch=={FIRE3D_TORCH} torchvision=={FIRE3D_TORCHVISION} torchaudio=={FIRE3D_TORCHAUDIO} --index-url https://download.pytorch.org/whl/cu128",
        f"git clone https://github.com/xiahongchi/Fire3D.git {FIRE3D_SOURCE}",
        f"cd {FIRE3D_SOURCE} && git checkout --detach {FIRE3D_REVISION}",
        f"python -m pip install -e '{FIRE3D_SOURCE}[dev]'",
        f"git clone https://github.com/yyfz/Pi3.git {PI3_SOURCE}",
        f"cd {PI3_SOURCE} && git checkout --detach {PI3_SOURCE_REVISION}",
        "python -m pip install spconv-cu118==2.3.8",
        "python -m pip install --no-build-isolation 'git+https://github.com/NVlabs/nvdiffrast.git@253ac4fcea7de5f396371124af597e6cc957bfae'",
        "python -m pip install --no-build-isolation 'git+https://github.com/facebookresearch/pytorch3d.git@75ebeeaea0908c5527e7b1e305fbc7681382db47'",
        "python -m pip install --no-build-isolation 'git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8'",
        "python -m pip install --no-build-isolation 'git+https://github.com/JeffreyXiang/FlexGEMM.git@6dd94a859c26ee8246888502eada3dd8ad85532e'",
        f"git clone https://github.com/facebookresearch/dinov3.git {FIRE3D_SOURCE}/third_party/dinov3",
        f"cd {FIRE3D_SOURCE}/third_party/dinov3 && git checkout --detach 31703e4cbf1ccb7c4a72daa1350405f86754b6d1",
        f"rm -rf {FIRE3D_SOURCE}/trellis2_x2/CuMesh/third_party/cubvh/third_party/eigen && git clone --depth 1 --branch 3.4.0 https://gitlab.com/libeigen/eigen.git {FIRE3D_SOURCE}/trellis2_x2/CuMesh/third_party/cubvh/third_party/eigen",
        f"rm -rf {FIRE3D_SOURCE}/trellis2_x2/o-voxel/third_party/eigen && git clone --depth 1 --branch 3.4.0 https://gitlab.com/libeigen/eigen.git {FIRE3D_SOURCE}/trellis2_x2/o-voxel/third_party/eigen",
        f"python -m pip install --no-build-isolation --no-deps {FIRE3D_SOURCE}/trellis2_x2/CuMesh",
        f"python -m pip install --no-build-isolation --no-deps {FIRE3D_SOURCE}/trellis2_x2/o-voxel",
    )
    .env(
        {
            "FIRE3D_ROOT": FIRE3D_SOURCE,
            "PI3_ROOT": PI3_SOURCE,
            "PYTHONPATH": f"{FIRE3D_SOURCE}:{PI3_SOURCE}",
            "HF_HOME": f"{FIRE3D_SOURCE}/checkpoints/huggingface",
            "HUGGINGFACE_HUB_CACHE": f"{FIRE3D_SOURCE}/checkpoints/huggingface/hub",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        }
    )
    .add_local_python_source("modal_fire3d", "modal_world")
)


def prepare_runtime_cache(root: str = FIRE3D_RUNTIME_CACHE_MOUNT) -> dict[str, str]:
    """Point all runtime-generated compiler/autotune caches at one persistent root.

    This is opt-in: callers must mount ``FIRE3D_RUNTIME_CACHE_VOLUME`` at
    ``FIRE3D_RUNTIME_CACHE_MOUNT``. The official baseline functions do not use
    this helper, so their protocol behavior stays unchanged.
    """
    import os
    import shutil
    from pathlib import Path

    base = Path(root)
    paths = {
        "TORCH_HOME": base / "torch",
        "CUDA_CACHE_PATH": base / "cuda",
        "TORCH_EXTENSIONS_DIR": base / "torch-extensions",
        "TORCHINDUCTOR_CACHE_DIR": base / "torchinductor",
        "TRITON_CACHE_DIR": base / "triton",
        "FLEX_GEMM_AUTOTUNE_CACHE_PATH": base / "flex-gemm" / "autotune_cache.json",
    }
    for path in paths.values():
        directory = path.parent if path.suffix else path
        directory.mkdir(parents=True, exist_ok=True)
    flex_cache = paths["FLEX_GEMM_AUTOTUNE_CACHE_PATH"]
    packaged_flex_cache = Path.home() / ".flex_gemm" / "autotune_cache.json"
    if not flex_cache.exists() and packaged_flex_cache.is_file():
        shutil.copy2(packaged_flex_cache, flex_cache)
    for key, value in paths.items():
        os.environ[key] = str(value)
    os.environ["FLEX_GEMM_USE_AUTOTUNE_CACHE"] = "1"
    os.environ["FLEX_GEMM_AUTOSAVE_AUTOTUNE_CACHE"] = "1"
    return {key: str(value) for key, value in paths.items()}
