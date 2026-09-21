"""Versioned mesh operations; no Blender/Modal import needed for discovery."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath

REVISION = "mesh-operations.v1-bpy420-xatlas009-r5"
P3SAM_REVISION = "p3sam.e96be065-w67717446-sonata-df998974-v1"
XPART_REVISION = "xpart-lite.e96be065-hf67717446-v1"
HUNYUAN_PAINT_REVISION = "hunyuan3d-paint-v2.1-0b946776-l40s-v1"
RESULT_CONTRACT = "modal-3d.operation-result.v1"
MAX_BYTES = 512 * 1024 * 1024
MIMES = {".glb": "model/gltf-binary", ".obj": "model/obj", ".blend": "application/x-blender",
         ".json": "application/json", ".png": "image/png"}


def number(default, minimum, maximum, integer=False):
    return {"type": "integer" if integer else "number", "default": default,
            "minimum": minimum, "maximum": maximum}


def enum(default, values):
    return {"type": "string", "default": default, "enum": list(values)}


def integer_array(default, minimum=0, maximum=255, max_items=256):
    return {"type": "array", "default": list(default), "minItems": 1, "maxItems": max_items,
            "items": {"type": "integer", "minimum": minimum, "maximum": maximum}}


UV_OPTIONS = {"resolution": number(1024, 64, 4096, True),
              "padding": number(8, 1, 64, True), "texels_per_unit": number(0, 0, 10000)}
BAKE_OPTIONS = {"resolution": number(1024, 64, 4096, True),
                "padding": number(8, 1, 64, True),
                "ray_distance": number(0.05, 0.000001, 1000)}
SPECS = {
    "inspect_mesh": {"label": "Inspect mesh", "inputs": ["asset"], "options": {}},
    "mesh_cleanup": {"label": "Clean mesh", "inputs": ["asset"], "options": {
        "merge_distance": number(0.00001, 0, 0.1),
        "remove_loose": {"type": "boolean", "default": True}}},
    "mesh_repair": {"label": "Repair mesh", "inputs": ["asset"], "options": {
        "merge_distance": number(0.00001, 0, 0.1),
        "max_hole_edges": number(8, 3, 100, True)}},
    "decimate": {"label": "Decimate mesh", "inputs": ["asset"], "options": {
        "target_faces": number(20000, 4, 2000000, True)}},
    "retopology": {"label": "QuadriFlow retopology", "inputs": ["asset"], "options": {
        "target_faces": number(4000, 16, 100000, True),
        "preserve_boundary": {"type": "boolean", "default": True},
        "preserve_sharp": {"type": "boolean", "default": True},
        "seed": number(0, 0, 2147483647, True)}},
    "uv_unwrap": {"label": "xatlas UV unwrap", "inputs": ["asset"], "options": UV_OPTIONS},
    "texture_bake": {"label": "Rebake PBR", "inputs": ["source", "target"], "options": BAKE_OPTIONS},
    "segment_parts": {
        "label": "P3-SAM part segmentation",
        "inputs": ["asset"],
        "options": {
            "point_num": number(100000, 10000, 200000, True),
            "prompt_num": number(400, 32, 800, True),
            "threshold": number(0.95, 0.0, 1.0),
            "post_process": {"type": "boolean", "default": True},
            "seed": number(42, 0, 2147483647, True),
            "prompt_bs": number(32, 1, 128, True),
        },
        "worker_app": "modal-3d-p3sam",
        "revision": P3SAM_REVISION,
        "resource": "gpu",
        "required_roles": ["primary-glb", "parts-manifest", "face-labels", "quality-report"],
    },
    "complete_parts": {
        "label": "X-Part lite part completion",
        "inputs": ["asset", "parts_manifest", "face_labels"],
        "options": {
            "part_index": number(0, 0, 255, True),
            "seed": number(42, 0, 2147483647, True),
            "num_inference_steps": number(50, 1, 100, True),
            "octree_resolution": number(512, 128, 512, True),
        },
        "worker_app": "modal-3d-xpart",
        "revision": XPART_REVISION,
        "resource": "gpu",
        "required_roles": ["primary-glb", "assembly-preview", "quality-report"],
    },
    "filter_parts": {
        "label": "Select / merge / exclude parts",
        "inputs": ["asset", "parts_manifest", "face_labels"],
        "input_mimes": {"asset": MIMES[".glb"], "parts_manifest": MIMES[".json"],
                        "face_labels": MIMES[".json"]},
        "options": {
            "part_indices": integer_array([0]),
            "mode": enum("keep", ["keep", "exclude"]),
        },
        "required_roles": ["primary-glb", "quality-report"],
    },
    "texture_generate": {
        "label": "Hunyuan3D-Paint 2.1 reference texture",
        "inputs": ["asset", "reference_image"],
        "input_mimes": {"asset": MIMES[".glb"], "reference_image": MIMES[".png"]},
        "options": {
            "preserve_geometry": {"type": "boolean", "default": True},
        },
        "worker_app": "modal-3d-hunyuan-paint",
        "revision": HUNYUAN_PAINT_REVISION,
        "resource": "gpu",
        "required_roles": ["primary-glb", "material-report", "quality-report"],
    },
}

def spec_for(operation):
    try:
        return SPECS[operation]
    except KeyError as exc:
        raise ValueError(f"unsupported operation: {operation}") from exc


def revision_for(operation):
    return spec_for(operation).get("revision", REVISION)


def worker_for(operation):
    return spec_for(operation).get("worker_app", "modal-3d-mesh")


def required_roles_for(operation):
    return list(spec_for(operation).get("required_roles", ["primary-glb", "quality-report"]))


def input_mimes_for(operation):
    spec = spec_for(operation)
    declared = spec.get("input_mimes", {})
    return {name: declared.get(name, MIMES[".glb"]) for name in spec["inputs"]}


def options_for(operation, options=None):
    spec_for(operation)
    if options is not None and not isinstance(options, dict):
        raise ValueError("options must be an object")
    schemas = spec_for(operation)["options"]
    unknown = set(options or {}) - set(schemas)
    if unknown:
        raise ValueError(f"unknown options: {sorted(unknown)}")
    result = {k: v["default"] for k, v in schemas.items()}
    result.update(options or {})
    for name, value in result.items():
        schema = schemas[name]
        kind = schema["type"]
        if kind == "boolean":
            valid = type(value) is bool
        elif kind == "integer":
            valid = type(value) is int and schema["minimum"] <= value <= schema["maximum"]
        elif kind == "number":
            valid = type(value) in (int, float) and math.isfinite(value) and schema["minimum"] <= value <= schema["maximum"]
        elif kind == "string":
            valid = isinstance(value, str) and value in schema.get("enum", [value])
        elif kind == "array":
            items = schema["items"]
            valid = (isinstance(value, list) and schema["minItems"] <= len(value) <= schema["maxItems"]
                     and len(set(value)) == len(value)
                     and all(type(item) is int and items["minimum"] <= item <= items["maximum"] for item in value))
        else:
            valid = False
        if not valid:
            raise ValueError(f"invalid option {name}: expected {schema}")
    if "resolution" in result and result["padding"] * 4 >= result["resolution"]:
        raise ValueError("padding must be less than one quarter of resolution")
    return result


def safe_relative(value):
    if not isinstance(value, str) or not value or any(c in value for c in "\\:\x00"):
        raise ValueError("artifact path must be a POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("unsafe artifact path")
    return path.as_posix()


def confined(root, value):
    root = Path(root).resolve()
    path = (root / safe_relative(value)).resolve()
    if not path.is_relative_to(root):
        raise ValueError("artifact escapes volume")
    return path


def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_descriptor(value):
    if not isinstance(value, dict):
        raise TypeError("artifact must be an object")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("sha256", ""))):
        raise ValueError("invalid artifact SHA256")
    if type(value.get("bytes")) is not int or not 0 < value["bytes"] <= MAX_BYTES:
        raise ValueError("invalid artifact bytes")
    safe_relative(value.get("path"))
    if value.get("mime") not in MIMES.values():
        raise ValueError("unsupported artifact MIME")
    return dict(value)


def request_key(operation, inputs, options):
    return hashlib.sha256(json.dumps({"operation": operation, "revision": revision_for(operation),
        "inputs": {k: {f: v[f] for f in ("sha256", "bytes", "mime")} for k, v in inputs.items()},
        "options": options}, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def capabilities():
    return [{
        "id": op,
        "operation": f"modal-3d.asset.{op}.v1",
        "version": "1",
        "revision": revision_for(op),
        "name": spec["label"],
        "inputs": spec["inputs"],
        "options": spec["options"],
        "worker_app": worker_for(op),
        "entrypoint": {"kind": "class_method", "class_name": "Model", "method_name": "run_job"},
        "execution": {"resource": spec.get("resource", "cpu"), "max_containers": 1},
        "verification": "experimental",
    } for op, spec in SPECS.items()]
