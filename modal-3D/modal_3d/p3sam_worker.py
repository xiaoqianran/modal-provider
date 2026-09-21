from __future__ import annotations

import hashlib
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

APP_NAME = "modal-3d-p3sam"
GPU = "A100-80GB"
SOURCE_REPO = "Tencent-Hunyuan/Hunyuan3D-Part"
SOURCE_REVISION = "e96be065375438962375b55326416291342958a7"
P3SAM_WEIGHT_REVISION = "677174466c53571e8bacd5050dff5948734a1a4d"
SONATA_REPO = "facebook/sonata"
SONATA_REVISION = "df99897472c09f91ba9288da0a034aacffc0b010"
SRC = PurePosixPath("/opt/hunyuan3d-part")
WEIGHT = PurePosixPath("/models/p3sam/p3sam.safetensors")
SONATA_WEIGHT = PurePosixPath("/models/sonata/sonata.pth")
PATCH = Path(__file__).parent / "patches/p3sam.patch"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-p3sam-weights", create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)

download_image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install("huggingface_hub==0.30.2", "hf_xet==1.1.9", uv_version="0.12.5")
)

runtime_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.11")
    .apt_install("git", "build-essential", "ninja-build", "libgl1", "libglib2.0-0", "libgomp1")
    .uv_pip_install(
        "torch==2.4.0",
        "torchvision==0.19.0",
        index_url="https://download.pytorch.org/whl/cu124",
        uv_version="0.12.5",
    )
    .uv_pip_install(
        "numpy==2.1.2", "scipy==1.16.3", "scikit-learn==1.7.2",
        "trimesh==4.8.3", "fpsample==0.3.3", "numba==0.61.2",
        "tqdm==4.67.1", "addict==2.4.0", "timm==1.0.20",
        "packaging==25.0", "wheel==0.45.1", "setuptools==80.9.0", "huggingface_hub==0.30.2", "safetensors==0.6.2",
        "spconv-cu124==2.3.8", uv_version="0.12.5",
    )
    .run_commands(
        "python -m pip install --no-deps 'https://data.pyg.org/whl/torch-2.4.0%2Bcu124/torch_scatter-2.1.2%2Bpt24cu124-cp311-cp311-linux_x86_64.whl'",
        "python -m pip install --no-build-isolation 'flash-attn==2.7.4.post1'",
        f"git clone --filter=blob:none --no-checkout https://github.com/{SOURCE_REPO}.git {SRC} && "
        f"git -C {SRC} sparse-checkout init --cone && "
        f"git -C {SRC} sparse-checkout set P3-SAM XPart/partgen/models/sonata && "
        f"git -C {SRC} checkout {SOURCE_REVISION}",
    )
    .add_local_file(PATCH, "/tmp/p3sam.patch", copy=True)
    .run_commands(
        f"git -C {SRC} apply --check /tmp/p3sam.patch && git -C {SRC} apply /tmp/p3sam.patch",
        "python -m pip check",
    )
    .env({
        "PYTHONPATH": f"{SRC}/P3-SAM:{SRC}/XPart/partgen",
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
    memory=8192,
    timeout=60 * 60,
    max_containers=1,
    secrets=[modal.Secret.from_name("huggingface")],
)
def sync_weights() -> dict:
    from huggingface_hub import hf_hub_download

    started = time.perf_counter()
    p3sam = hf_hub_download(
        repo_id="tencent/Hunyuan3D-Part",
        filename="p3sam/p3sam.safetensors",
        revision=P3SAM_WEIGHT_REVISION,
        local_dir="/models",
    )
    sonata = hf_hub_download(
        repo_id=SONATA_REPO,
        filename="sonata.pth",
        revision=SONATA_REVISION,
        local_dir="/models/sonata",
    )
    weights.commit()
    return {
        "elapsed_s": time.perf_counter() - started,
        "p3sam": str(p3sam),
        "sonata": str(sonata),
        "bytes": Path(p3sam).stat().st_size + Path(sonata).stat().st_size,
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


def _palette(label: int) -> list[int]:
    d = hashlib.sha256(f"p3sam:{label}".encode()).digest()
    return [64 + d[0] % 192, 64 + d[1] % 192, 64 + d[2] % 192, 255]


def _run_segment(model, source: Path, output: Path, options: dict) -> dict:
    import numpy as np
    import trimesh

    mesh = trimesh.load(source, force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError("P3-SAM input must contain a triangle mesh")

    source_face_count = len(mesh.faces)
    source_vertex_count = len(mesh.vertices)
    _aabb, face_ids, result_mesh = model.predict_aabb(
        mesh,
        point_num=options["point_num"],
        prompt_num=options["prompt_num"],
        threshold=options["threshold"],
        post_process=options["post_process"],
        save_path=str(output),
        save_mid_res=False,
        show_info=False,
        clean_mesh_flag=False,
        seed=options["seed"],
        is_parallel=False,
        prompt_bs=options["prompt_bs"],
    )
    face_ids = np.asarray(face_ids, dtype=np.int64)
    if len(result_mesh.faces) != source_face_count or len(face_ids) != source_face_count:
        raise RuntimeError("P3-SAM changed topology; source face mapping cannot be guaranteed")

    labels = [int(x) for x in np.unique(face_ids) if int(x) >= 0]
    if not labels:
        raise RuntimeError("P3-SAM returned no parts")

    preview = result_mesh.copy()
    colors = np.zeros((source_face_count, 4), dtype=np.uint8)
    for label in labels:
        colors[face_ids == label] = _palette(label)
    colors[face_ids < 0] = [32, 32, 32, 255]
    preview.visual.face_colors = colors
    preview_path = output / "segmented.glb"
    preview.export(preview_path)

    face_labels_path = output / "face-labels.json"
    face_labels_path.write_text(json.dumps({
        "schema": "modal-3d.face-labels.v1",
        "face_count": source_face_count,
        "labels": face_ids.tolist(),
    }, separators=(",", ":")), encoding="utf-8")

    parts = []
    rows = [{"file": preview_path.name, "role": "primary-glb"}]
    for ordinal, label in enumerate(labels):
        indices = np.flatnonzero(face_ids == label)
        part = result_mesh.submesh([indices], append=True, repair=False)
        if not isinstance(part, trimesh.Trimesh) or len(part.faces) == 0:
            continue
        filename = f"part-{ordinal:04d}.glb"
        part_path = output / filename
        part.export(part_path)
        points = result_mesh.vertices[result_mesh.faces[indices].reshape(-1)]
        role = f"part-{ordinal:04d}"
        rows.append({"file": filename, "role": role})
        parts.append({
            "part_id": role,
            "source_label": label,
            "role": role,
            "face_count": len(indices),
            "bbox": [points.min(axis=0).tolist(), points.max(axis=0).tolist()],
            "name": None,
            "name_source": None,
        })

    manifest_path = output / "parts-manifest.json"
    manifest_path.write_text(json.dumps({
        "schema": "modal-3d.part-set.v1",
        "source_space": "unchanged",
        "source_face_count": source_face_count,
        "source_vertex_count": source_vertex_count,
        "face_labels_role": "face-labels",
        "parts": parts,
    }, allow_nan=False, indent=2), encoding="utf-8")

    assigned = int(np.sum(face_ids >= 0))
    quality_path = output / "quality-report.json"
    quality_path.write_text(json.dumps({
        "schema": "modal-3d.quality-report.v1",
        "backend": "P3-SAM",
        "source_revision": SOURCE_REVISION,
        "part_count": len(parts),
        "face_count": source_face_count,
        "assigned_faces": assigned,
        "unassigned_faces": source_face_count - assigned,
        "coverage": assigned / source_face_count,
        "topology_preserved": True,
        "face_mapping_preserved": True,
        "options": options,
    }, allow_nan=False, indent=2), encoding="utf-8")

    rows.extend([
        {"file": manifest_path.name, "role": "parts-manifest"},
        {"file": face_labels_path.name, "role": "face-labels"},
        {"file": quality_path.name, "role": "quality-report"},
    ])
    return {
        "artifacts": rows,
        "metrics": {
            "part_count": len(parts),
            "face_count": source_face_count,
            "coverage": assigned / source_face_count,
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
        if not Path(WEIGHT).is_file() or not Path(SONATA_WEIGHT).is_file():
            raise FileNotFoundError("P3-SAM weights are not prepared; run sync_weights on CPU")
        sys.path.insert(0, str(SRC / "XPart/partgen"))
        sys.path.insert(0, str(SRC / "P3-SAM"))
        from demo.auto_mask import AutoMask
        self.model = AutoMask(str(WEIGHT))

    @modal.method()
    def run_job(self, request: dict, options: dict | None = None) -> dict:
        started = time.monotonic()
        if not isinstance(request, dict) or request.get("operation") != "segment_parts":
            raise ValueError("P3-SAM only supports segment_parts")
        inputs = request.get("inputs")
        if not isinstance(inputs, dict) or set(inputs) != {"asset"}:
            raise ValueError("segment_parts requires exactly one asset input")
        normalized = options_for("segment_parts", options)

        root = Path("/artifacts").resolve()
        artifacts.reload()
        desc = validate_descriptor(inputs["asset"])
        if desc["mime"] != MIMES[".glb"]:
            raise ValueError("segment_parts input must be GLB")
        source = confined(root, desc["path"])
        validate_file(source, desc["mime"])
        if source.stat().st_size != desc["bytes"] or digest_file(source) != desc["sha256"]:
            raise ValueError("segment_parts input integrity mismatch")

        key = request_key("segment_parts", {"asset": desc}, normalized)
        destination = root / "operations" / "segment_parts" / key
        manifest = destination / "result.json"
        if manifest.is_file():
            result = json.loads(manifest.read_text(encoding="utf-8"))
            for artifact in result["artifacts"]:
                path = confined(root, artifact["path"])
                validate_file(path, artifact["mime"])
                if digest_file(path) != artifact["sha256"]:
                    raise ValueError("cached P3-SAM artifact corrupted")
            return {**result, "cache_hit": True}

        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="p3sam-") as temporary:
            output = Path(temporary)
            runtime = _run_segment(self.model, source, output, normalized)
            descriptors = [
                _descriptor(output / item["file"], item["role"], destination, root)
                for item in runtime["artifacts"]
            ]
            roles = [x["role"] for x in descriptors]
            required = {"primary-glb", "parts-manifest", "face-labels", "quality-report"}
            if not required.issubset(roles) or len(roles) != len(set(roles)):
                raise ValueError("P3-SAM result roles are incomplete or duplicated")

            result = {
                "contract": RESULT_CONTRACT,
                "operation": "segment_parts",
                "revision": revision_for("segment_parts"),
                "request_key": key,
                "inputs": {"asset": desc},
                "options": normalized,
                "artifacts": descriptors,
                "metrics": runtime["metrics"],
                "timing": {"total_s": time.monotonic() - started},
                "cache_hit": False,
            }
            destination.mkdir(parents=True, exist_ok=True)
            for descriptor in descriptors:
                shutil.copyfile(output / descriptor["filename"], destination / descriptor["filename"])
            pending = destination / "result.pending"
            pending.write_text(json.dumps(result, allow_nan=False, indent=2), encoding="utf-8")
            os.replace(pending, manifest)
            artifacts.commit()
            return result
