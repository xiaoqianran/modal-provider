from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import modal

from .common import ARTIFACT_VOLUME, _glb_json_document
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
from .hunyuan2_1_plus_plus import (
    DINO_ID,
    DINO_REVISION,
    MODEL_ID,
    MODEL_REVISION,
    REALESRGAN_CKPT,
    REALESRGAN_SHA256,
    SRC,
    _pin_hf_main,
    download_image,
    runtime_image,
)

APP_NAME = "modal-3d-hunyuan-paint"
GPU = "L40S"
MODEL_DIR = "/models/Hunyuan3D-2.1"
HF_CACHE = "/models/hf-cache"

app = modal.App(APP_NAME)
weights = modal.Volume.from_name("modal-3d-hunyuan-paint-weights", create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)


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
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=MODEL_DIR,
        allow_patterns=["hunyuan3d-paintpbr-v2-1/*"],
    )
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        cache_dir=HF_CACHE,
        allow_patterns=["hunyuan3d-paintpbr-v2-1/*"],
    )
    _pin_hf_main(HF_CACHE, MODEL_ID, MODEL_REVISION)
    snapshot_download(DINO_ID, revision=DINO_REVISION, cache_dir=HF_CACHE)
    _pin_hf_main(HF_CACHE, DINO_ID, DINO_REVISION)

    ckpt = Path(REALESRGAN_CKPT)
    if not ckpt.exists():
        import urllib.request

        urllib.request.urlretrieve(
            "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
            ckpt,
        )
    digest = hashlib.sha256(ckpt.read_bytes()).hexdigest()
    if digest != REALESRGAN_SHA256:
        raise RuntimeError(f"RealESRGAN checksum mismatch: {digest}")
    paint_dir = Path(MODEL_DIR) / "hunyuan3d-paintpbr-v2-1"
    if not paint_dir.is_dir():
        raise RuntimeError("Hunyuan3D-Paint weights missing after sync")
    weights.commit()
    return {
        "elapsed_s": time.perf_counter() - started,
        "bytes": sum(p.stat().st_size for p in Path("/models").rglob("*") if p.is_file()),
        "model_revision": MODEL_REVISION,
        "dino_revision": DINO_REVISION,
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


def _checked_input(root: Path, value: dict, mime: str) -> tuple[dict, Path]:
    desc = validate_descriptor(value)
    if desc["mime"] != mime:
        raise ValueError(f"expected {mime}, got {desc['mime']}")
    path = confined(root, desc["path"])
    validate_file(path, mime)
    if path.stat().st_size != desc["bytes"] or digest_file(path) != desc["sha256"]:
        raise ValueError("input integrity mismatch")
    return desc, path


def _mesh_stats(path: Path) -> dict:
    import numpy as np
    import trimesh

    mesh = trimesh.load(path, force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("paint input/output must resolve to one mesh")
    bounds = np.asarray(mesh.bounds, dtype=float)
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "bounds": bounds.tolist(),
    }


def _material_report(path: Path) -> dict:
    doc = _glb_json_document(path)
    rows = []
    for index, material in enumerate(doc.get("materials", [])):
        pbr = material.get("pbrMetallicRoughness", {})
        rows.append({
            "index": index,
            "baseColorTexture": "baseColorTexture" in pbr,
            "metallicRoughnessTexture": "metallicRoughnessTexture" in pbr,
            "normalTexture": "normalTexture" in material,
            "occlusionTexture": "occlusionTexture" in material,
            "emissiveTexture": "emissiveTexture" in material,
        })
    return {
        "schema": "modal-3d.material-report.v1",
        "backend": "Hunyuan3D-Paint-2.1",
        "materials": rows,
        "material_count": len(rows),
        "embedded_images": len(doc.get("images", [])),
        "pbr_expected": ["baseColor", "metallicRoughness", "normal"],
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
        import sys
        import torch

        sys.path.insert(0, f"{SRC}/hy3dpaint")
        os.chdir(SRC)
        from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

        if torch.cuda.get_device_capability() != (8, 9):
            raise RuntimeError(f"expected L40S sm_89, got {torch.cuda.get_device_name()}")
        if not (Path(MODEL_DIR) / "hunyuan3d-paintpbr-v2-1").is_dir():
            raise RuntimeError("Paint weights are not provisioned; run sync_weights on CPU")

        config = Hunyuan3DPaintConfig(max_num_view=6, resolution=512)
        config.multiview_pretrained_path = MODEL_ID
        config.dino_ckpt_path = DINO_ID
        config.realesrgan_ckpt_path = REALESRGAN_CKPT
        t0 = time.perf_counter()
        self.paint_pipe = Hunyuan3DPaintPipeline(config)
        torch.cuda.synchronize()
        self.load_s = time.perf_counter() - t0

    @modal.method()
    def run_job(self, request: dict, options: dict | None = None) -> dict:
        import numpy as np
        import torch

        started = time.monotonic()
        if not isinstance(request, dict) or request.get("operation") != "texture_generate":
            raise ValueError("Hunyuan Paint worker only supports texture_generate")
        inputs = request.get("inputs")
        if not isinstance(inputs, dict) or set(inputs) != {"asset", "reference_image"}:
            raise ValueError("texture_generate requires asset and reference_image")
        normalized = options_for("texture_generate", options)

        root = Path("/artifacts").resolve()
        artifacts.reload()
        asset_desc, source = _checked_input(root, inputs["asset"], MIMES[".glb"])
        image_desc, image = _checked_input(root, inputs["reference_image"], MIMES[".png"])
        checked = {"asset": asset_desc, "reference_image": image_desc}
        key = request_key("texture_generate", checked, normalized)
        destination = root / "operations" / "texture_generate" / key
        result_path = destination / "result.json"
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            for desc in result["artifacts"]:
                path = confined(root, desc["path"])
                validate_file(path, desc["mime"])
                if digest_file(path) != desc["sha256"]:
                    raise ValueError("cached Paint artifact corrupted")
            return {**result, "cache_hit": True}

        before = _mesh_stats(source)
        with tempfile.TemporaryDirectory(prefix="hunyuan-paint-") as temporary:
            work = Path(temporary)
            output_obj = work / "textured_mesh.obj"
            self.paint_pipe.last_timings = {}
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            paint_t0 = time.perf_counter()
            self.paint_pipe(
                mesh_path=str(source),
                image_path=str(image),
                output_mesh_path=str(output_obj),
                use_remesh=not normalized["preserve_geometry"],
                save_glb=True,
            )
            torch.cuda.synchronize()
            paint_s = time.perf_counter() - paint_t0
            output_glb = output_obj.with_suffix(".glb")
            validate_file(output_glb, MIMES[".glb"])
            after = _mesh_stats(output_glb)
            bounds_delta = float(np.max(np.abs(np.asarray(before["bounds"]) - np.asarray(after["bounds"]))))
            topology_preserved = before["faces"] == after["faces"] and bounds_delta <= 1e-5
            if normalized["preserve_geometry"] and not topology_preserved:
                raise ValueError(
                    f"strict texture mode changed geometry: faces {before['faces']} -> {after['faces']}, "
                    f"bounds_delta={bounds_delta}"
                )

            material = _material_report(output_glb)
            material_path = work / "material-report.json"
            material_path.write_text(json.dumps(material, indent=2, allow_nan=False), encoding="utf-8")
            quality = {
                "schema": "modal-3d.quality-report.v1",
                "backend": "Hunyuan3D-Paint-2.1",
                "model_revision": MODEL_REVISION,
                "dino_revision": DINO_REVISION,
                "gpu": torch.cuda.get_device_name(),
                "paint_views": 6,
                "paint_resolution": 512,
                "preserve_geometry": normalized["preserve_geometry"],
                "source": before,
                "output": after,
                "bounds_max_abs_delta": bounds_delta,
                "topology_preserved_guard": topology_preserved,
                "paint_s": paint_s,
                "load_s": self.load_s,
                "paint_profile": dict(getattr(self.paint_pipe, "last_timings", {})),
                "peak_vram_allocated_gb": torch.cuda.max_memory_allocated() / 2**30,
                "peak_vram_reserved_gb": torch.cuda.max_memory_reserved() / 2**30,
            }
            quality_path = work / "quality-report.json"
            quality_path.write_text(json.dumps(quality, indent=2, allow_nan=False), encoding="utf-8")

            rows = [
                _descriptor(output_glb, "primary-glb", destination, root),
                _descriptor(material_path, "material-report", destination, root),
                _descriptor(quality_path, "quality-report", destination, root),
            ]
            result = {
                "contract": RESULT_CONTRACT,
                "operation": "texture_generate",
                "revision": revision_for("texture_generate"),
                "request_key": key,
                "inputs": checked,
                "options": normalized,
                "artifacts": rows,
                "metrics": {
                    "paint_s": paint_s,
                    "source_faces": before["faces"],
                    "output_faces": after["faces"],
                    "topology_preserved": topology_preserved,
                    "material_count": material["material_count"],
                },
                "timing": {"total_s": time.monotonic() - started},
                "cache_hit": False,
            }
            destination.mkdir(parents=True, exist_ok=True)
            for desc in rows:
                shutil.copyfile(work / desc["filename"], destination / desc["filename"])
            pending = destination / "result.pending"
            pending.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
            os.replace(pending, result_path)
            artifacts.commit()
            return result
