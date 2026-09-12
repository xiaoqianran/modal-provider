"""Run deployed FIRE3D from fresh outputs and retain local acceptance evidence."""

import argparse
import hashlib
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import modal


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def inspect_glb(path):
    import numpy as np
    import trimesh

    raw = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", raw)
    if magic != b"glTF" or version != 2 or length != len(raw):
        raise ValueError(f"invalid GLB header: {path}")
    scene = trimesh.load(path, force="scene", process=False)
    if not scene.geometry:
        raise ValueError(f"empty GLB scene: {path}")
    meshes = []
    for name, mesh in scene.geometry.items():
        if not len(mesh.vertices) or not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
            raise ValueError(f"empty/nonfinite mesh: {path} / {name}")
        if mesh.faces.min() < 0 or mesh.faces.max() >= len(mesh.vertices):
            raise ValueError(f"invalid triangle indices: {path} / {name}")
        material = getattr(mesh.visual, "material", None)
        texture = getattr(material, "baseColorTexture", None)
        meshes.append({
            "name": name, "vertices": len(mesh.vertices), "faces": len(mesh.faces),
            "material": type(material).__name__,
            "base_color_texture_size": list(texture.size) if texture is not None else None,
        })
    if not np.isfinite(scene.bounds).all():
        raise ValueError(f"invalid world bounds: {path}")
    return {
        "file": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "bounds": scene.bounds.tolist(), "meshes": meshes,
        "geometry_nodes": len(scene.graph.nodes_geometry),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()
    if not args.run_id.isascii() or not all(c.isalnum() or c in "-_" for c in args.run_id):
        raise ValueError("invalid run ID")
    local = Path("acceptance") / args.run_id
    local.mkdir(parents=True, exist_ok=False)
    print(f"Evidence directory: {local.resolve()}", flush=True)
    preload = modal.Function.from_name("modal-world-fire3d", "preload_official_single_image")
    print("Checking/downloading official input and model bundles...", flush=True)
    save_json(local / "preload.json", preload.remote())
    function = modal.Function.from_name("modal-world-fire3d", "official_single_image_smoke")
    call = function.spawn(run_id=args.run_id)
    save_json(local / "call.json", {"call_id": call.object_id, "run_id": args.run_id})
    print(f"H100 inference call: {call.object_id}", flush=True)
    result = call.get()
    save_json(local / "result.json", result)
    print(f"Inference complete: {result['elapsed_s']} s, {result['num_objects']} objects", flush=True)
    volume = modal.Volume.from_name("fire3d-output")
    reports = []
    for item in result["files"]:
        relative = Path(item["path"])
        if relative.suffix not in {".json", ".log"} and relative.name not in {
            "canonical.glb", "predicted_textured_world_scene.glb"
        }:
            continue
        target = local / "output" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            for chunk in volume.read_file(f"acceptance/{args.run_id}/{relative.as_posix()}"):
                handle.write(chunk)
        if target.stat().st_size != item["bytes"]:
            raise ValueError(f"download size mismatch: {target}")
        if target.suffix == ".glb":
            report = inspect_glb(target)
            report["path"] = relative.as_posix()
            reports.append(report)
            print(f"Validated {relative}: {target.stat().st_size} bytes", flush=True)
    save_json(local / "glb_validation.json", reports)
    assert len(reports) == result["num_objects"] + 1
    print(f"PASS: {len(reports)} GLBs parsed and validated", flush=True)


if __name__ == "__main__":
    main()
