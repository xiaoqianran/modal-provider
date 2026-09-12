"""Independent Modal runtime for the official Fire3D release."""

from __future__ import annotations

import modal

from .runtime import (
    FIRE3D_BUILD_ARTIFACT_MOUNT,
    FIRE3D_BUILD_ARTIFACT_VOLUME,
    FIRE3D_FLASH_ATTN_TAG,
    FIRE3D_FLASH_ATTN_VERSION,
    FIRE3D_GPU,
    FIRE3D_PYTORCH3D_TAG,
    FIRE3D_PYTORCH3D_VERSION,
    FIRE3D_REVISION,
    FIRE3D_SINGLE_IMAGE_SCENE,
    FIRE3D_SOURCE,
    fire3d_image,
)

app = modal.App("modal-world-fire3d")

models = modal.Volume.from_name("fire3d-models", create_if_missing=True)
data = modal.Volume.from_name("fire3d-data", create_if_missing=True)
outputs = modal.Volume.from_name("fire3d-output", create_if_missing=True)
build_artifacts = modal.Volume.from_name(FIRE3D_BUILD_ARTIFACT_VOLUME)

VOLUMES = {
    f"{FIRE3D_SOURCE}/checkpoints": models,
    f"{FIRE3D_SOURCE}/data": data,
    "/outputs": outputs,
    FIRE3D_BUILD_ARTIFACT_MOUNT: build_artifacts,
}


def _ensure_flash_attn(*, verify_cuda: bool = False) -> dict:
    """Install the verified prebuilt wheel; optionally execute one H100 kernel smoke."""
    import hashlib
    import importlib.metadata
    import json
    import subprocess
    import sys
    from pathlib import Path

    artifact_root = Path(FIRE3D_BUILD_ARTIFACT_MOUNT) / FIRE3D_FLASH_ATTN_TAG
    manifest_path = artifact_root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"missing Fire3D flash-attn manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("smoke_status") != "passed":
        raise RuntimeError(f"Fire3D flash-attn artifact is not H100-verified: {manifest}")

    wheel_meta = manifest.get("wheel") or {}
    wheel_name = wheel_meta.get("file")
    wheel = artifact_root / wheel_name if wheel_name else None
    if wheel is None or not wheel.is_file():
        raise RuntimeError(f"missing Fire3D flash-attn wheel under {artifact_root}")

    expected_sha = wheel_meta.get("sha256")
    if expected_sha:
        digest = hashlib.sha256()
        with wheel.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_sha = digest.hexdigest()
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"Fire3D flash-attn wheel sha256 mismatch: expected={expected_sha} actual={actual_sha}"
            )

    try:
        installed_version = importlib.metadata.version("flash-attn")
    except importlib.metadata.PackageNotFoundError:
        installed_version = None
    if installed_version != FIRE3D_FLASH_ATTN_VERSION:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", str(wheel)],
            check=True,
        )

    result = {
        "version": FIRE3D_FLASH_ATTN_VERSION,
        "wheel": wheel.name,
        "sha256": expected_sha,
        "cuda_verified": False,
    }
    if verify_cuda:
        import torch
        from flash_attn import flash_attn_func

        capability = torch.cuda.get_device_capability()
        if capability != (9, 0):
            raise RuntimeError(f"expected H100/sm90, got compute capability {capability}")
        q = torch.randn((1, 32, 4, 64), device="cuda", dtype=torch.bfloat16)
        out = flash_attn_func(q, q, q, causal=False)
        torch.cuda.synchronize()
        if out.shape != q.shape or not torch.isfinite(out).all():
            raise RuntimeError("Fire3D flash-attn H100 smoke failed")
        result["cuda_verified"] = True
        result["gpu"] = torch.cuda.get_device_name()
        result["capability"] = list(capability)
    return result


def _ensure_pytorch3d(*, verify_cuda: bool = False) -> dict:
    """Install the verified sm90 PyTorch3D wheel; optionally execute one CUDA op."""
    import hashlib
    import importlib.metadata
    import json
    import subprocess
    import sys
    from pathlib import Path

    artifact_root = Path(FIRE3D_BUILD_ARTIFACT_MOUNT) / FIRE3D_PYTORCH3D_TAG
    manifest_path = artifact_root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"missing Fire3D PyTorch3D manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("smoke_status") != "passed":
        raise RuntimeError(f"Fire3D PyTorch3D artifact is not H100-verified: {manifest}")

    wheel_meta = manifest.get("wheel") or {}
    wheel_name = wheel_meta.get("file")
    wheel = artifact_root / wheel_name if wheel_name else None
    if wheel is None or not wheel.is_file():
        raise RuntimeError(f"missing Fire3D PyTorch3D wheel under {artifact_root}")

    expected_sha = wheel_meta.get("sha256")
    if expected_sha:
        digest = hashlib.sha256()
        with wheel.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_sha = digest.hexdigest()
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"Fire3D PyTorch3D wheel sha256 mismatch: expected={expected_sha} actual={actual_sha}"
            )

    try:
        installed_version = importlib.metadata.version("pytorch3d")
    except importlib.metadata.PackageNotFoundError:
        installed_version = None
    if verify_cuda or installed_version != FIRE3D_PYTORCH3D_VERSION:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                str(wheel),
            ],
            check=True,
        )

    result = {
        "version": FIRE3D_PYTORCH3D_VERSION,
        "wheel": wheel.name,
        "sha256": expected_sha,
        "cuda_verified": False,
    }
    if verify_cuda:
        import torch
        from pytorch3d.ops import sample_farthest_points

        capability = torch.cuda.get_device_capability()
        if capability != (9, 0):
            raise RuntimeError(f"expected H100/sm90, got compute capability {capability}")
        points = torch.randn((1, 32, 3), device="cuda", dtype=torch.float32)
        sampled, indices = sample_farthest_points(points, K=8)
        torch.cuda.synchronize()
        if sampled.shape != (1, 8, 3) or indices.shape != (1, 8):
            raise RuntimeError("Fire3D PyTorch3D H100 smoke failed")
        result["cuda_verified"] = True
        result["gpu"] = torch.cuda.get_device_name()
        result["capability"] = list(capability)
    return result


@app.function(image=fire3d_image, cpu=4.0, memory=16384, volumes=VOLUMES, timeout=2 * 60 * 60)
def preload_official_single_image(scene_id: str = FIRE3D_SINGLE_IMAGE_SCENE) -> dict:
    """Download and verify the official model bundle plus one whitelisted sample."""
    import subprocess
    import sys
    import time
    from pathlib import Path

    root = Path(FIRE3D_SOURCE)
    started = time.perf_counter()
    build_artifacts.reload()
    flash_attn = _ensure_flash_attn()
    commands = (
        [sys.executable, "-m", "fire3d", "download", "--models"],
        [
            sys.executable,
            "-m",
            "fire3d",
            "download",
            "--data",
            "--dataset",
            "single_image",
            "--scene-id",
            scene_id,
        ],
    )
    for command in commands:
        subprocess.run(command, cwd=root, check=True)
    models.commit()
    data.commit()

    required = (
        root / "checkpoints/Fire3D/perception/model.pt",
        root / "checkpoints/Fire3D/reconstruction/flows/ss/model.pt",
        root / "data/single_image/single_image_valid.txt",
        root / f"data/single_image/data/{scene_id}/rgb.jpeg",
        root / f"data/single_image/data/{scene_id}/aligned_pcd.ply",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Fire3D preload incomplete: {missing}")
    return {
        "revision": FIRE3D_REVISION,
        "scene_id": scene_id,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "flash_attn": flash_attn,
        "required": [str(path) for path in required],
    }


@app.function(
    image=fire3d_image,
    gpu=FIRE3D_GPU,
    cpu=32.0,
    memory=65536,
    volumes=VOLUMES,
    timeout=3 * 60 * 60,
)
def official_single_image_smoke(
    scene_id: str = FIRE3D_SINGLE_IMAGE_SCENE,
    *,
    force: bool = False,
    render: bool = False,
    run_id: str = "",
    background_policy: str = "official",
) -> dict:
    """Run official (default) or explicitly selected repaired single-image protocol."""
    import json
    import shutil
    import subprocess
    import sys
    import time
    from pathlib import Path

    import torch

    root = Path(FIRE3D_SOURCE)
    from modal_fire3d.background_policy import write_background_protocol

    if background_policy not in {"official", "observed_single_image"}:
        raise ValueError(f"unknown background policy: {background_policy}")
    if background_policy != "official" and not run_id:
        raise ValueError("background repair requires a fresh run_id")
    if run_id and (not run_id.isascii() or not all(c.isalnum() or c in "-_" for c in run_id)):
        raise ValueError("run_id must contain only ASCII letters, digits, hyphens or underscores")
    if not scene_id.isascii() or not scene_id.isalnum():
        raise ValueError("scene_id must be an ASCII alphanumeric identifier")
    actual_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if actual_revision != FIRE3D_REVISION:
        raise RuntimeError(f"unexpected FIRE3D checkout revision: {actual_revision}")
    models.reload()
    data.reload()
    outputs.reload()
    build_artifacts.reload()
    flash_attn = _ensure_flash_attn(verify_cuda=True)
    pytorch3d = _ensure_pytorch3d(verify_cuda=True)

    required = (
        root / "checkpoints/Fire3D/perception/model.pt",
        root / "data/single_image/single_image_valid.txt",
        root / f"data/single_image/data/{scene_id}/rgb.jpeg",
        root / f"data/single_image/data/{scene_id}/aligned_pcd.ply",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(
            "Fire3D release assets are missing; run preload_official_single_image first: "
            + ", ".join(missing)
        )

    output_root = Path("/outputs") / f"official-single-image-{scene_id}"
    if run_id:
        output_root = Path("/outputs") / "acceptance" / run_id
        if output_root.exists():
            raise FileExistsError(f"acceptance run must use a fresh output directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    if force and output_root.exists():
        shutil.rmtree(output_root)

    command = [
        sys.executable,
        "-m",
        "fire3d",
        "infer",
        "--dataset",
        "single_image",
        "--scene-id",
        scene_id,
        "--output-root",
        str(output_root),
        "--gpu",
        "0",
    ]
    protocol_path = write_background_protocol(root, output_root, "single_image", background_policy)
    if protocol_path:
        command.extend(["--protocol", str(protocol_path)])
    if not render:
        command.append("--skip-render")
    if not force and not run_id:
        command.append("--skip-existing")

    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    torch.cuda.synchronize()
    elapsed_s = time.perf_counter() - started
    (output_root / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (output_root / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    receipt = {
        "revision": actual_revision,
        "run_id": run_id,
        "command": command,
        "returncode": completed.returncode,
        "elapsed_s": round(elapsed_s, 3),
        "fresh_output": bool(run_id),
        "background_policy": background_policy,
    }
    (output_root / "execution.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    outputs.commit()
    if completed.returncode != 0:
        raise RuntimeError(
            f"Fire3D official single-image inference failed ({completed.returncode}): "
            f"stdout={completed.stdout[-10000:]} stderr={completed.stderr[-10000:]}"
        )

    recon_root = output_root / "reconstruction" / scene_id
    inference_summary_path = recon_root / "inference_summary.json"
    scene_glb = recon_root / "appearance/predicted_textured_world_scene.glb"
    appearance_summary = recon_root / "appearance/appearance_summary.json"
    protocol = output_root / "resolved_protocol.json"
    run_summary = output_root / "summary.json"
    required_outputs = (
        inference_summary_path,
        scene_glb,
        appearance_summary,
        protocol,
        run_summary,
    )
    missing_outputs = [str(path) for path in required_outputs if not path.is_file()]
    if missing_outputs:
        raise RuntimeError(f"Fire3D output contract incomplete: {missing_outputs}")

    inference_summary = json.loads(inference_summary_path.read_text(encoding="utf-8"))
    if inference_summary.get("status") != "complete":
        raise RuntimeError(f"Fire3D reconstruction status is not complete: {inference_summary}")

    object_glbs = sorted(recon_root.rglob("canonical.glb"))
    if not object_glbs:
        raise RuntimeError("Fire3D produced no canonical object GLBs")

    files = []
    total_bytes = 0
    for path in sorted(output_root.rglob("*")):
        if path.is_file():
            size = path.stat().st_size
            total_bytes += size
            files.append({"path": path.relative_to(output_root).as_posix(), "bytes": size})
    outputs.commit()

    return {
        "execution": receipt,
        "revision": FIRE3D_REVISION,
        "protocol": protocol_path.stem if protocol_path else "fire3d_single_image_v1",
        "scene_id": scene_id,
        "gpu": torch.cuda.get_device_name(),
        "capability": list(torch.cuda.get_device_capability()),
        "torch": str(torch.__version__),
        "flash_attn": flash_attn,
        "pytorch3d": pytorch3d,
        "elapsed_s": round(elapsed_s, 3),
        "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
        "num_objects": len(object_glbs),
        "scene_glb": str(scene_glb),
        "scene_glb_bytes": scene_glb.stat().st_size,
        "object_glbs": [str(path) for path in object_glbs],
        "total_output_bytes": total_bytes,
        "files": files,
        "stdout_tail": completed.stdout[-10000:],
    }
