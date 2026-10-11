"""Operation request validation, artifact paths, and capability projection."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath

from .registry import MAX_BYTES, MIMES, REVISION, SPECS, PLANNED_SPECS


def spec_for(operation):
    if operation in PLANNED_SPECS:
        raise ValueError(f'operation not implemented: {operation}')
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


def required_inputs_for(operation):
    spec = spec_for(operation)
    return list(spec.get("required_inputs", spec["inputs"]))


def validate_input_names(operation, inputs):
    if not isinstance(inputs, dict):
        raise TypeError("inputs must be an object")
    spec = spec_for(operation)
    names = set(inputs)
    allowed = set(spec["inputs"])
    required = set(required_inputs_for(operation))
    missing = required - names
    unknown = names - allowed
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing inputs: {sorted(missing)}")
        if unknown:
            details.append(f"unknown inputs: {sorted(unknown)}")
        raise ValueError("; ".join(details))
    return dict(inputs)


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
        "required_inputs": required_inputs_for(op),
        "options": spec["options"],
        "worker_app": worker_for(op),
        "entrypoint": {"kind": "class_method", "class_name": "Model", "method_name": "run_job"},
        "execution": {"resource": spec.get("resource", "cpu"), "max_containers": 1},
        "verification": "experimental",
    } for op, spec in SPECS.items()] + [{
        "id": op,
        "operation": f"modal-3d.asset.{op}.v1",
        "version": "1",
        "name": spec["label"],
        "inputs": spec["inputs"],
        "execution": {"resource": spec["resource"]},
        "status": "planned",
        "available": False,
        "verification": "not_implemented",
    } for op, spec in PLANNED_SPECS.items()]
