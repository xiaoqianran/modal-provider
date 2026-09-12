from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import modal

ARTIFACT_VOLUME = "modal-build-artifacts"
TAG = "fire3d-flash-attn-py310-cu128-torch271-sm90-v1"
FLASH_ATTN_REVISION = "89c5a7dd4e6a8644575bd0c04a286f48c42763ec"  # v2.7.3
PYTHON, CUDA, TORCH = "3.10", "12.8.1", "2.7.1"
CUDA_ARCH, GPU = "9.0", "H100"
WHEELS, LICENSES, OUT = Path("/tmp/wheels"), Path("/tmp/licenses"), Path("/out")


def sh(cmd: str, *, cwd: str | Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(["bash", "-lc", cmd], cwd=cwd, env=env, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


app = modal.App("modal-build-fire3d-flash-attn-sm90")
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)
image = (
    modal.Image.from_registry(f"nvidia/cuda:{CUDA}-devel-ubuntu22.04", add_python=PYTHON)
    .apt_install("git", "build-essential", "ninja-build")
    .run_commands(
        "python -m pip install --upgrade pip setuptools wheel packaging ninja psutil",
        f"python -m pip install torch=={TORCH} --index-url https://download.pytorch.org/whl/cu128",
        "python -m pip install numpy==1.26.4 einops==0.8.2",
    )
)


@app.function(
    image=image,
    cpu=16.0,
    memory=32768,
    volumes={"/out": artifacts},
    timeout=2 * 60 * 60,
    max_containers=1,
)
def build() -> dict:
    shutil.rmtree(WHEELS, ignore_errors=True)
    shutil.rmtree(LICENSES, ignore_errors=True)
    WHEELS.mkdir(parents=True)
    LICENSES.mkdir(parents=True)

    src = Path("/tmp/flash-attention")
    shutil.rmtree(src, ignore_errors=True)
    sh(f"git clone --recursive https://github.com/Dao-AILab/flash-attention.git {src}")
    sh(f"git checkout --detach {FLASH_ATTN_REVISION}", cwd=src)
    sh("git submodule update --init --recursive", cwd=src)
    shutil.copy2(src / "LICENSE", LICENSES / "flash-attention-LICENSE.txt")

    env = os.environ.copy()
    env.update(
        {
            "CUDA_HOME": "/usr/local/cuda",
            "CC": "gcc",
            "CXX": "g++",
            "TORCH_CUDA_ARCH_LIST": CUDA_ARCH,
            "FLASH_ATTN_CUDA_ARCHS": "90",
            "MAX_JOBS": "8",
            "FLASH_ATTENTION_FORCE_BUILD": "TRUE",
        }
    )
    sh(
        f"{sys.executable} -m pip wheel . --no-build-isolation --no-deps -w {WHEELS}",
        cwd=src,
        env=env,
    )

    wheels = sorted(WHEELS.glob("flash_attn-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one flash_attn wheel, got {[path.name for path in wheels]}")
    wheel = wheels[0]

    out_dir = OUT / TAG
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / wheel.name
    shutil.copy2(wheel, target)
    shutil.copy2(LICENSES / "flash-attention-LICENSE.txt", out_dir / "LICENSE.txt")

    manifest = {
        "tag": TAG,
        "bundle_kind": "fire3d-flash-attention",
        "public_release": True,
        "python": PYTHON,
        "cuda": CUDA,
        "torch": TORCH,
        "cuda_arch": CUDA_ARCH,
        "target_gpu": GPU,
        "source": "Dao-AILab/flash-attention",
        "source_revision": FLASH_ATTN_REVISION,
        "source_version": "2.7.3",
        "license": "BSD-3-Clause",
        "wheel": {
            "file": wheel.name,
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
        },
        "smoke_required": ["gpu-sm90", "flash_attn_func-bf16"],
        "smoke_status": "pending",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    artifacts.commit()
    return manifest


@app.function(
    image=image,
    gpu=GPU,
    cpu=2.0,
    memory=8192,
    volumes={"/out": artifacts},
    timeout=10 * 60,
    max_containers=1,
)
def smoke() -> dict:
    import torch

    artifacts.reload()
    out_dir = OUT / TAG
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"missing build manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wheel_name = manifest.get("wheel", {}).get("file")
    wheel = out_dir / wheel_name if wheel_name else None
    if wheel is None or not wheel.exists():
        raise RuntimeError(f"missing flash-attn wheel in {out_dir}")

    expected_sha = manifest.get("wheel", {}).get("sha256")
    actual_sha = sha256(wheel)
    if expected_sha and actual_sha != expected_sha:
        raise RuntimeError(
            f"flash-attn wheel sha256 mismatch: expected={expected_sha} actual={actual_sha}"
        )

    sh(f"{sys.executable} -m pip install --force-reinstall --no-deps {wheel}")

    capability = torch.cuda.get_device_capability()
    if capability != (9, 0):
        raise RuntimeError(f"expected H100/sm90, got compute capability {capability}")

    from flash_attn import flash_attn_func

    q = torch.randn((1, 32, 4, 64), device="cuda", dtype=torch.bfloat16)
    result = flash_attn_func(q, q, q, causal=False)
    torch.cuda.synchronize()
    if result.shape != q.shape or not torch.isfinite(result).all():
        raise RuntimeError("Fire3D flash-attn sm90 CUDA smoke failed")

    manifest["smoke_status"] = "passed"
    manifest["smoke_result"] = {
        "gpu_name": torch.cuda.get_device_name(),
        "compute_capability": list(capability),
        "torch": str(torch.__version__),
        "cuda": str(torch.version.cuda),
        "wheel_sha256": actual_sha,
        "test": "flash_attn_func-bf16",
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    artifacts.commit()
    return manifest
