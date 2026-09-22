"""Validate, execute and atomically publish immutable operation artifacts."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .common import _glb_json_document, validate_glb
from .operations import (
    MAX_BYTES,
    MIMES,
    RESULT_CONTRACT,
    confined,
    digest_file,
    input_mimes_for,
    options_for,
    request_key,
    revision_for,
    validate_descriptor,
    validate_input_names,
)


def validate_file(path, mime):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("artifact is absent, empty or oversized")
    if mime == MIMES[".glb"]:
        validate_glb(path)
        doc = _glb_json_document(path)
        if not doc.get("meshes"):
            raise ValueError("GLB contains no meshes")
        for row in doc.get("buffers", []) + doc.get("images", []):
            if row.get("uri") and not row["uri"].startswith("data:"):
                raise ValueError("external GLB resources are unsupported; embed all resources")
        if doc.get("skins") or doc.get("animations"):
            raise ValueError("P1 accepts static assets; rigged/animated assets require explicit unbinding")
    elif mime == MIMES[".json"]:
        json.loads(path.read_text(encoding="utf-8"))
    elif mime == MIMES[".png"]:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
    elif mime == MIMES[".obj"]:
        with path.open(encoding="utf-8") as stream:
            if not any(line.startswith("f ") for line in stream):
                raise ValueError("OBJ has no faces")
    elif mime == MIMES[".blend"]:
        with path.open("rb") as stream:
            if stream.read(7) != b"BLENDER":
                raise ValueError("invalid Blender file")


def execute_blender(operation, inputs, options, output):
    request = output / "request.json"
    request.write_text(json.dumps({"operation": operation, "inputs": {k: str(v) for k, v in inputs.items()},
                                   "options": options, "output": str(output)}), encoding="utf-8")
    script = Path(__file__).with_name("mesh_runtime.py")
    completed = subprocess.run([sys.executable, str(script), str(request)],
                               capture_output=True, text=True, timeout=3300, check=False)
    if completed.returncode:
        raise RuntimeError(f"mesh runtime failed: {completed.stderr[-4000:]} {completed.stdout[-1000:]}")
    return json.loads((output / "runtime.json").read_text(encoding="utf-8"))


def run_operation_job(volume, operation, inputs, options=None, *, root="/artifacts", execute=execute_blender):
    started = time.monotonic()
    options = options_for(operation, options)
    inputs = validate_input_names(operation, inputs)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    volume.reload()
    checked, paths = {}, {}
    expected_mimes = input_mimes_for(operation)
    for name, value in inputs.items():
        desc = validate_descriptor(value)
        if desc["mime"] != expected_mimes[name]:
            raise ValueError(f"{operation} input {name} must be {expected_mimes[name]}")
        path = confined(root, desc["path"])
        validate_file(path, desc["mime"])
        if path.stat().st_size != desc["bytes"] or digest_file(path) != desc["sha256"]:
            raise ValueError(f"input integrity mismatch: {name}")
        checked[name], paths[name] = desc, path
    key = request_key(operation, checked, options)
    destination = root / "operations" / operation / key
    manifest = destination / "result.json"
    if manifest.is_file():
        result = json.loads(manifest.read_text(encoding="utf-8"))
        for desc in result["artifacts"]:
            path = confined(root, desc["path"])
            validate_file(path, desc["mime"])
            if digest_file(path) != desc["sha256"]:
                raise ValueError("cached operation artifact corrupted")
        return {**result, "cache_hit": True}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mesh-operation-") as temporary:
        output = Path(temporary)
        runtime = execute(operation, paths, options, output)
        artifacts = []
        for item in runtime["artifacts"]:
            source = confined(output, item["file"])
            mime = MIMES[source.suffix]
            validate_file(source, mime)
            digest = digest_file(source)
            artifacts.append({"id": f"art_{digest}", "role": item["role"], "mime": mime,
                "mediaType": mime, "bytes": source.stat().st_size, "sha256": digest,
                "digest": f"sha256:{digest}", "filename": source.name,
                "path": (destination / source.name).relative_to(root).as_posix()})
        if not artifacts or len({a["role"] for a in artifacts}) != len(artifacts):
            raise ValueError("operation must produce unique artifact roles")
        result = {"contract": RESULT_CONTRACT, "operation": operation, "revision": revision_for(operation),
                  "request_key": key, "inputs": checked, "options": options,
                  "artifacts": artifacts, "metrics": runtime.get("metrics", {}),
                  "timing": {"total_s": time.monotonic() - started}, "cache_hit": False}
        # Only validated files enter the mounted volume; result.json is the completion marker.
        import shutil
        destination.mkdir(parents=True, exist_ok=True)
        for desc in artifacts:
            shutil.copyfile(output / desc["filename"], destination / desc["filename"])
        pending = destination / "result.pending"
        pending.write_text(json.dumps(result, allow_nan=False, indent=2), encoding="utf-8")
        os.replace(pending, manifest)
        volume.commit()
        return result
