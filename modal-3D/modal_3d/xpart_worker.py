from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

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
)

APP_NAME = "modal-3d-xpart"
GPU = "A100-80GB"
SOURCE_REPO = "Tencent-Hunyuan/Hunyuan3D-Part"
SOURCE_REVISION = "e96be065375438962375b55326416291342958a7"
WEIGHT_REPO = "tencent/Hunyuan3D-Part"
WEIGHT_REVISION = "677174466c53571e8bacd5050dff5948734a1a4d"
SRC = PurePosixPath("/opt/hunyuan3d-part")
MODEL_ROOT = PurePosixPath("/models/tencent/Hunyuan3D-Part")
PATCH = Path(__file__).parent / "patches/xpart.patch"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-xpart-weights", create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)

download_image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install("huggingface_hub==0.30.2", "hf_xet==1.1.9", uv_version="0.12.5")
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.11")
    .apt_install("git", "build-essential", "ninja-build", "libgl1", "libglib2.0-0", "libgomp1")
    .uv_pip_install(
        "torch==2.4.0", "torchvision==0.19.0",
        index_url="https://download.pytorch.org/whl/cu124",
        uv_version="0.12.5",
    )
    .uv_pip_install(
        "numpy==2.1.2", "scipy==1.16.3", "scikit-learn==1.7.2",
        "scikit-image==0.25.2", "trimesh==4.8.3", "fpsample==0.3.3",
        "numba==0.61.2", "tqdm==4.67.1", "addict==2.4.0",
        "easydict==1.13", "einops==0.8.1", "pymeshlab==2023.12.post3",
        "omegaconf==2.3.0", "timm==1.0.20", "torchdiffeq==0.2.5",
        "diffusers==0.35.1", "safetensors==0.6.2", "huggingface_hub==0.34.4",
        "spconv-cu124==2.3.8", "wheel==0.45.1", "setuptools==80.9.0",
        uv_version="0.12.5",
    )
    .run_commands(
        "python -m pip install --no-deps 'https://data.pyg.org/whl/torch-2.4.0%2Bcu124/torch_scatter-2.1.2%2Bpt24cu124-cp311-cp311-linux_x86_64.whl'",
        "python -m pip install --no-deps 'https://data.pyg.org/whl/torch-2.4.0%2Bcu124/torch_cluster-1.6.3%2Bpt24cu124-cp311-cp311-linux_x86_64.whl'",
        "python -m pip install --no-build-isolation 'flash-attn==2.7.4.post1'",
        f"git clone --filter=blob:none --no-checkout https://github.com/{SOURCE_REPO}.git {SRC} && "
        f"git -C {SRC} sparse-checkout init --cone && "
        f"git -C {SRC} sparse-checkout set XPart && "
        f"git -C {SRC} checkout {SOURCE_REVISION}",
    )
    .add_local_file(PATCH, "/tmp/xpart.patch", copy=True)
    .run_commands(
        f"git -C {SRC} apply --check /tmp/xpart.patch && git -C {SRC} apply /tmp/xpart.patch",
        "python -m pip check",
    )
    .env({
        "PYTHONPATH": f"{SRC}/XPart",
        "HY3DGEN_MODELS": "/models",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        "PYTHONUNBUFFERED": "1",
    })
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

    started = time.perf_counter()
    path = snapshot_download(
        repo_id=WEIGHT_REPO,
        revision=WEIGHT_REVISION,
        local_dir=str(MODEL_ROOT),
        allow_patterns=[
            "model/*",
            "conditioner/*",
            "shapevae/*",
            "scheduler/*",
        ],
    )
    required = [
        MODEL_ROOT / "model/model.safetensors",
        MODEL_ROOT / "conditioner/conditioner.safetensors",
        MODEL_ROOT / "shapevae/shapevae.safetensors",
        MODEL_ROOT / "scheduler/config.json",
    ]
    for item in required:
        if not Path(item).is_file():
            raise FileNotFoundError(item)
    weights.commit()
    return {
        "path": path,
        "bytes": sum(Path(item).stat().st_size for item in required),
        "elapsed_s": time.perf_counter() - started,
        "revision": WEIGHT_REVISION,
    }


def _descriptor(path: Path, role: str, destination: Path, root: Path) -> dict:
    mime = MIMES[path.suffix]
    validate_file(path, mime)
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


def _read_json(root: Path, desc: dict) -> dict:
    path = confined(root, desc["path"])
    if desc["mime"] != MIMES[".json"]:
        raise ValueError("expected JSON artifact")
    if path.stat().st_size != desc["bytes"] or digest_file(path) != desc["sha256"]:
        raise ValueError("JSON artifact integrity mismatch")
    return json.loads(path.read_text(encoding="utf-8"))


def _run_completion(pipeline, source: Path, manifest: dict, labels_doc: dict, output: Path, options: dict) -> dict:
    import numpy as np
    import torch
    import trimesh

    parts = manifest.get("parts")
    if manifest.get("schema") != "modal-3d.part-set.v1" or not isinstance(parts, list):
        raise ValueError("invalid PartSet manifest")
    index = options["part_index"]
    if index >= len(parts):
        raise ValueError(f"part_index {index} out of range for {len(parts)} parts")
    selected = parts[index]
    bbox = np.asarray(selected["bbox"], dtype=np.float32)
    if bbox.shape != (2, 3) or not np.isfinite(bbox).all():
        raise ValueError("invalid selected part bbox")

    mesh = trimesh.load(source, force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError("X-Part input must be one triangle mesh")
    labels = np.asarray(labels_doc.get("labels"), dtype=np.int64)
    if len(labels) != len(mesh.faces):
        raise ValueError("face labels no longer align with source mesh")

    generator = torch.Generator(device="cuda").manual_seed(options["seed"])
    generated_scene, _ = pipeline(
        mesh=mesh,
        aabb=bbox[None, ...],
        seed=options["seed"],
        generator=generator,
        num_inference_steps=options["num_inference_steps"],
        octree_resolution=options["octree_resolution"],
        output_type="trimesh",
        enable_pbar=False,
    )
    geometries = list(generated_scene.geometry.values())
    if len(geometries) != 1:
        raise RuntimeError(f"selected-part completion returned {len(geometries)} geometries")
    generated = geometries[0]

    part_path = output / "completed-part.glb"
    generated.export(part_path)

    source_label = int(selected["source_label"])
    keep_faces = np.flatnonzero(labels != source_label)
    remainder = mesh.submesh([keep_faces], append=True, repair=False)
    assembly = trimesh.Scene()
    if isinstance(remainder, trimesh.Trimesh) and len(remainder.faces):
        assembly.add_geometry(remainder, node_name="source-remainder")
    assembly.add_geometry(generated, node_name="completed-part")
    assembly_path = output / "assembly-preview.glb"
    assembly.export(assembly_path)

    report = {
        "schema": "modal-3d.quality-report.v1",
        "backend": "X-Part-lite",
        "source_revision": SOURCE_REVISION,
        "weight_revision": WEIGHT_REVISION,
        "part_index": index,
        "part_id": selected.get("part_id"),
        "source_label": source_label,
        "source_face_count": len(mesh.faces),
        "removed_source_faces": int(np.sum(labels == source_label)),
        "generated_faces": len(generated.faces),
        "bbox": bbox.tolist(),
        "source_space": "preserved",
        "release": "lite",
        "limitations": [
            "current public X-Part release is the lite version",
            "semantic natural-language part names are not guaranteed",
        ],
        "options": options,
    }
    quality = output / "quality-report.json"
    quality.write_text(json.dumps(report, allow_nan=False, indent=2), encoding="utf-8")
    return {
        "artifacts": [
            {"file": part_path.name, "role": "primary-glb"},
            {"file": assembly_path.name, "role": "assembly-preview"},
            {"file": quality.name, "role": "quality-report"},
        ],
        "metrics": {
            "generated_faces": len(generated.faces),
            "removed_source_faces": report["removed_source_faces"],
        },
    }


@app.cls(
    image=runtime_image,
    gpu=GPU,
    volumes={"/models": weights, "/artifacts": artifacts},
    timeout=60 * 60,
    scaledown_window=60,
    max_containers=1,
)
class Model:
    @modal.enter()
    def load(self):
        required = [
            MODEL_ROOT / "model/model.safetensors",
            MODEL_ROOT / "conditioner/conditioner.safetensors",
            MODEL_ROOT / "shapevae/shapevae.safetensors",
        ]
        if not all(Path(x).is_file() for x in required):
            raise FileNotFoundError("X-Part weights are not prepared; run sync_weights on CPU")
        sys.path.insert(0, str(SRC / "XPart"))
        import torch
        from partgen.partformer_pipeline import PartFormerPipeline
        self.pipeline = PartFormerPipeline.from_pretrained(
            model_path=WEIGHT_REPO,
            verbose=False,
        )
        self.pipeline.to(device="cuda", dtype=torch.float32)

    @modal.method()
    def run_job(self, request: dict, options: dict | None = None) -> dict:
        started = time.monotonic()
        if not isinstance(request, dict) or request.get("operation") != "complete_parts":
            raise ValueError("X-Part worker only supports complete_parts")
        inputs = request.get("inputs")
        required_inputs = {"asset", "parts_manifest", "face_labels"}
        if not isinstance(inputs, dict) or set(inputs) != required_inputs:
            raise ValueError("complete_parts requires asset, parts_manifest, face_labels")
        normalized = options_for("complete_parts", options)

        root = Path("/artifacts").resolve()
        artifacts.reload()
        checked = {name: validate_descriptor(inputs[name]) for name in required_inputs}
        source_desc = checked["asset"]
        if source_desc["mime"] != MIMES[".glb"]:
            raise ValueError("complete_parts asset must be GLB")
        source = confined(root, source_desc["path"])
        validate_file(source, source_desc["mime"])
        if source.stat().st_size != source_desc["bytes"] or digest_file(source) != source_desc["sha256"]:
            raise ValueError("source GLB integrity mismatch")

        manifest_doc = _read_json(root, checked["parts_manifest"])
        labels_doc = _read_json(root, checked["face_labels"])
        key = request_key("complete_parts", checked, normalized)
        destination = root / "operations" / "complete_parts" / key
        result_path = destination / "result.json"
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            for desc in result["artifacts"]:
                path = confined(root, desc["path"])
                validate_file(path, desc["mime"])
                if digest_file(path) != desc["sha256"]:
                    raise ValueError("cached X-Part artifact corrupted")
            return {**result, "cache_hit": True}

        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xpart-") as temporary:
            out = Path(temporary)
            runtime = _run_completion(self.pipeline, source, manifest_doc, labels_doc, out, normalized)
            descriptors = [
                _descriptor(out / item["file"], item["role"], destination, root)
                for item in runtime["artifacts"]
            ]
            result = {
                "contract": RESULT_CONTRACT,
                "operation": "complete_parts",
                "revision": revision_for("complete_parts"),
                "request_key": key,
                "inputs": checked,
                "options": normalized,
                "artifacts": descriptors,
                "metrics": runtime["metrics"],
                "timing": {"total_s": time.monotonic() - started},
                "cache_hit": False,
            }
            destination.mkdir(parents=True, exist_ok=True)
            for desc in descriptors:
                shutil.copyfile(out / desc["filename"], destination / desc["filename"])
            pending = destination / "result.pending"
            pending.write_text(json.dumps(result, allow_nan=False, indent=2), encoding="utf-8")
            os.replace(pending, result_path)
            artifacts.commit()
            return result
