from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import modal

from .common import ARTIFACT_VOLUME
from .operation_runner import validate_file
from .operations import (
    MIMES,
    RESULT_CONTRACT,
    confined,
    digest_file,
    options_for,
    request_key,
    revision_for,
    validate_descriptor,
    validate_input_names,
)

APP_NAME = "modal-3d-tokenrig"
GPU = "L40S"

SOURCE_REPO = "VAST-AI-Research/SkinTokens"
SOURCE_REVISION = "273b691d35989d71cd17ff2895fdc735097b92d1"
SRC = "/opt/skintokens"

WEIGHT_REPO = "VAST-AI/SkinTokens"
WEIGHT_REVISION = "79736ca"
QWEN_REPO = "Qwen/Qwen3-0.6B"
QWEN_REVISION = "c1899de"
MODEL_ROOT = "/models/tokenrig"
TOKENRIG_CKPT = (
    f"{MODEL_ROOT}/experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt"
)
SKIN_VAE_CKPT = f"{MODEL_ROOT}/experiments/skin_vae_2_10_32768/last.ckpt"
QWEN_CONFIG = f"{MODEL_ROOT}/models/Qwen3-0.6B"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-tokenrig-weights", create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)

download_image = modal.Image.debian_slim(python_version="3.11").uv_pip_install(
    "huggingface_hub==0.36.2",
    "hf_xet==1.1.9",
    uv_version="0.12.5",
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.11")
    .apt_install(
        "git",
        "build-essential",
        "libgl1",
        "libglib2.0-0",
        "libx11-6",
        "libxi6",
        "libxxf86vm1",
    )
    .uv_pip_install(
        "torch==2.7.0",
        "torchvision==0.22.0",
        "torchaudio==2.7.0",
        index_url="https://download.pytorch.org/whl/cu128",
        uv_version="0.12.5",
    )
    .uv_pip_install(
        "transformers>=4.57.0,<5",
        "diffusers>=0.35.0,<1",
        "python-box",
        "einops",
        "omegaconf",
        "lightning",
        "addict",
        "fast-simplification",
        "bpy==4.2.0",
        "trimesh",
        "open3d",
        "huggingface_hub==0.36.2",
        "gradio",
        "numpy>=1.26,<2.1",
        "bottle",
        "tornado",
        "requests",
        "scipy",
        "ninja",
        "packaging",
        "setuptools",
        "wheel",
        "tqdm",
        uv_version="0.12.5",
    )
    .run_commands(
        "python -m pip install -U pip setuptools wheel",
        "MAX_JOBS=4 pip install flash-attn==2.8.3 --no-build-isolation",
        f"git clone --filter=blob:none https://github.com/{SOURCE_REPO}.git {SRC} && "
        f"git -C {SRC} checkout {SOURCE_REVISION}",
        f"python -m py_compile {SRC}/src/model/tokenrig.py {SRC}/demo.py",
    )
    .env(
        {
            "PYTHONPATH": SRC,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PYTHONUNBUFFERED": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
)


@app.function(
    image=download_image,
    volumes={"/models": weights},
    cpu=4,
    memory=8192,
    timeout=60 * 60,
    max_containers=1,
)
def sync_weights() -> dict:
    from huggingface_hub import hf_hub_download, snapshot_download

    started = time.perf_counter()
    files = [
        "experiments/skin_vae_2_10_32768/last.ckpt",
        "experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt",
    ]
    for filename in files:
        hf_hub_download(
            repo_id=WEIGHT_REPO,
            revision=WEIGHT_REVISION,
            filename=filename,
            local_dir=MODEL_ROOT,
        )
    snapshot_download(
        repo_id=QWEN_REPO,
        revision=QWEN_REVISION,
        local_dir=QWEN_CONFIG,
        ignore_patterns=["*.bin", "*.safetensors"],
    )
    required = [
        Path(TOKENRIG_CKPT),
        Path(SKIN_VAE_CKPT),
        Path(QWEN_CONFIG) / "config.json",
    ]
    for item in required:
        if not item.is_file() or item.stat().st_size == 0:
            raise FileNotFoundError(item)
    weights.commit()
    return {
        "bytes": sum(item.stat().st_size for item in required),
        "elapsed_s": time.perf_counter() - started,
        "source_revision": SOURCE_REVISION,
        "weight_revision": WEIGHT_REVISION,
        "qwen_revision": QWEN_REVISION,
    }


def _descriptor(
    path: Path, role: str, destination: Path, root: Path, *, glb_mode: str = "static"
) -> dict:
    mime = MIMES[path.suffix]
    validate_file(path, mime, glb_mode=glb_mode)
    digest = digest_file(path)
    return {
        "id": f"art_{digest}",
        "role": role,
        "mime": mime,
        "mediaType": mime,
        "bytes": path.stat().st_size,
        "sha256": digest,
        "digest": f"sha256:{digest}",
        "filename": path.name,
        "path": (destination / path.name).relative_to(root).as_posix(),
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
        import subprocess

        if not Path(TOKENRIG_CKPT).is_file() or not Path(SKIN_VAE_CKPT).is_file():
            raise FileNotFoundError("TokenRig weights are not provisioned; run sync_weights")
        if not (Path(QWEN_CONFIG) / "config.json").is_file():
            raise FileNotFoundError("Qwen3 config is not provisioned; run sync_weights")

        os.chdir(SRC)
        qwen_link = Path(SRC) / "models" / "Qwen3-0.6B"
        qwen_link.parent.mkdir(parents=True, exist_ok=True)
        if not qwen_link.exists():
            qwen_link.symlink_to(QWEN_CONFIG, target_is_directory=True)

        # The released checkpoint stores the FSQ-CVAE path relative to repository root.
        vae_link = Path(SRC) / "experiments" / "skin_vae_2_10_32768"
        vae_link.parent.mkdir(parents=True, exist_ok=True)
        if not vae_link.exists():
            vae_link.symlink_to(Path(SKIN_VAE_CKPT).parent, target_is_directory=True)

        sys.path.insert(0, SRC)
        import demo

        self.demo = demo
        self.bpy_server = subprocess.Popen(
            [sys.executable, "bpy_server.py"],
            cwd=SRC,
            stdout=None,
            stderr=None,
        )
        demo.wait_for_bpy_server(timeout=60)
        started = time.perf_counter()
        demo.load_model(TOKENRIG_CKPT, None)
        self.load_s = time.perf_counter() - started

    @modal.exit()
    def stop(self):
        proc = getattr(self, "bpy_server", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()

    @modal.method()
    def run_job(self, request: dict, options: dict | None = None) -> dict:
        import bpy
        import numpy as np
        import torch

        started = time.monotonic()
        if not isinstance(request, dict) or request.get("operation") != "rig":
            raise ValueError("TokenRig worker only supports rig")

        inputs = validate_input_names("rig", request.get("inputs"))
        normalized = options_for("rig", options)
        root = Path("/artifacts").resolve()
        artifacts.reload()

        source_desc = validate_descriptor(inputs["asset"])
        if source_desc["mime"] != MIMES[".glb"]:
            raise ValueError("TokenRig input must be a GLB")
        source = confined(root, source_desc["path"])
        validate_file(source, MIMES[".glb"], glb_mode="static")
        if source.stat().st_size != source_desc["bytes"] or digest_file(source) != source_desc["sha256"]:
            raise ValueError("TokenRig input integrity mismatch")

        key = request_key("rig", {"asset": source_desc}, normalized)
        destination = root / "operations" / "rig" / key
        manifest = destination / "result.json"
        if manifest.is_file():
            result = json.loads(manifest.read_text(encoding="utf-8"))
            for desc in result["artifacts"]:
                cached = confined(root, desc["path"])
                validate_file(
                    cached,
                    desc["mime"],
                    glb_mode="rigged" if desc["mime"] == MIMES[".glb"] else "static",
                )
                if digest_file(cached) != desc["sha256"]:
                    raise ValueError("cached TokenRig artifact corrupted")
            return {**result, "cache_hit": True}

        torch.cuda.reset_peak_memory_stats()
        with tempfile.TemporaryDirectory(prefix="tokenrig-") as temporary:
            work = Path(temporary)
            output = work / "rigged.glb"
            infer_started = time.perf_counter()
            self.demo.run_rig(
                [source],
                normalized["top_k"],
                normalized["top_p"],
                normalized["temperature"],
                normalized["repetition_penalty"],
                normalized["num_beams"],
                False,
                normalized["preserve_texture_and_scale"],
                normalized["postprocess_skin"],
                [output],
                TOKENRIG_CKPT,
                None,
            )
            torch.cuda.synchronize()
            inference_s = time.perf_counter() - infer_started
            validate_file(output, MIMES[".glb"], glb_mode="rigged")

            # Re-open the exported file with bpy to verify hierarchy and normalized weights.
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.gltf(filepath=str(output), import_pack_images=True)
            armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
            if len(armatures) != 1:
                raise RuntimeError(f"TokenRig output has {len(armatures)} armatures")
            armature = armatures[0]
            bones = list(armature.data.bones)
            roots = [bone for bone in bones if bone.parent is None]
            if len(roots) != 1:
                raise RuntimeError(f"TokenRig hierarchy must have one root, found {len(roots)}")

            visited: set[str] = set()
            visiting: set[str] = set()

            def visit(bone):
                if bone.name in visiting:
                    raise RuntimeError("TokenRig skeleton contains a cycle")
                if bone.name in visited:
                    return
                visiting.add(bone.name)
                for child in bone.children:
                    visit(child)
                visiting.remove(bone.name)
                visited.add(bone.name)

            visit(roots[0])
            if len(visited) != len(bones):
                raise RuntimeError("TokenRig skeleton contains disconnected bones")

            weighted_vertices = 0
            invalid_weight_vertices = 0
            for obj in bpy.context.scene.objects:
                if obj.type != "MESH":
                    continue
                for vertex in obj.data.vertices:
                    weights_sum = sum(group.weight for group in vertex.groups)
                    if weights_sum > 0:
                        weighted_vertices += 1
                        if not np.isclose(weights_sum, 1.0, atol=1e-3):
                            invalid_weight_vertices += 1
            if weighted_vertices == 0 or invalid_weight_vertices:
                raise RuntimeError(
                    "TokenRig skin weights are missing or not normalized: "
                    f"weighted={weighted_vertices}, invalid={invalid_weight_vertices}"
                )

            rig_report = {
                "schema": "modal-3d.rig-report.v1",
                "backend": "TokenRig",
                "source_revision": SOURCE_REVISION,
                "weight_revision": WEIGHT_REVISION,
                "bones": len(bones),
                "root_bone": roots[0].name,
                "weighted_vertices": weighted_vertices,
                "invalid_weight_vertices": invalid_weight_vertices,
                "preserve_texture_and_scale": normalized["preserve_texture_and_scale"],
            }
            rig_path = work / "rig-report.json"
            rig_path.write_text(json.dumps(rig_report, indent=2), encoding="utf-8")
            quality = {
                "schema": "modal-3d.quality-report.v1",
                **rig_report,
                "load_s": self.load_s,
                "inference_s": inference_s,
                "gpu": torch.cuda.get_device_name(),
                "peak_vram_allocated_gb": torch.cuda.max_memory_allocated() / 2**30,
                "peak_vram_reserved_gb": torch.cuda.max_memory_reserved() / 2**30,
            }
            quality_path = work / "quality-report.json"
            quality_path.write_text(json.dumps(quality, indent=2), encoding="utf-8")

            descriptors = [
                _descriptor(output, "primary-glb", destination, root, glb_mode="rigged"),
                _descriptor(rig_path, "rig-report", destination, root),
                _descriptor(quality_path, "quality-report", destination, root),
            ]
            result = {
                "contract": RESULT_CONTRACT,
                "operation": "rig",
                "revision": revision_for("rig"),
                "request_key": key,
                "inputs": {"asset": source_desc},
                "options": normalized,
                "artifacts": descriptors,
                "metrics": rig_report,
                "timing": {
                    "inference_s": inference_s,
                    "total_s": time.monotonic() - started,
                },
                "cache_hit": False,
            }
            destination.mkdir(parents=True, exist_ok=True)
            for desc in descriptors:
                shutil.copyfile(work / desc["filename"], destination / desc["filename"])
            pending = destination / "result.pending"
            pending.write_text(json.dumps(result, indent=2), encoding="utf-8")
            os.replace(pending, manifest)
            artifacts.commit()
            return result
