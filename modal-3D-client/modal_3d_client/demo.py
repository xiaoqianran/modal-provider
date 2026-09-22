from __future__ import annotations

"""Offline demo provider.

When ``MODAL_3D_CLIENT_DEMO=1`` the sidecar advertises a fake capability
document and resolves every job through an in-memory store, so the bundled web
UI can be exercised end-to-end without a Modal account or a deployed worker.
This is a development affordance only; it never touches the Modal SDK.
"""

import hashlib
import json
import struct
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from modal_3d.operations import (
    MAX_BYTES,
    MIMES,
    SPECS,
    input_mimes_for,
    options_for,
    required_roles_for,
)

from .constants import (
    CANONICAL_SIZE,
    CLIENT_INPUT_PREFIX,
    CONTRACT,
    JOB_TRANSPORT,
    OPERATION,
    OUTPUT_MIME,
    OUTPUT_ROLE,
)

_MODELS = [
    {
        "id": "fastsam3d-plus-plus",
        "name": "FastSAM3D++",
        "description": "最快的彩色资产生成；vertex-color GLB",
        "status": "enabled",
        "output": "textured",
        "profiles": [
            {
                "id": "recommended",
                "name": "推荐 · Fast-SAM3D 加速",
                "options": {"dmd_interval": 1, "dmd_history": 5},
            },
            {
                "id": "full",
                "name": "全质量",
                "options": {"dmd_interval": 1, "dmd_history": 12},
            },
        ],
        "options": {
            "seed": {"type": "integer", "default": 42, "minimum": 0, "maximum": 4294967295},
        },
    },
    {
        "id": "hunyuan2-1-plus-plus",
        "name": "Hunyuan2.1++",
        "description": "高保真几何重建",
        "status": "enabled",
        "output": "geometry",
        "profiles": [
            {"id": "recommended", "name": "推荐", "options": {}},
        ],
        "options": {
            "seed": {"type": "integer", "default": 42, "minimum": 0, "maximum": 4294967295},
        },
    },
    {
        "id": "hermit-trellis2-plus-plus",
        "name": "Hermite-TRELLIS2++",
        "description": "PBR 纹理资产生成",
        "status": "enabled",
        "output": "textured",
        "profiles": [
            {"id": "recommended", "name": "推荐", "options": {}},
        ],
        "options": {
            "seed": {"type": "integer", "default": 42, "minimum": 0, "maximum": 4294967295},
        },
    },
    {
        "id": "pixal3d",
        "name": "Pixal3D",
        "description": "单图快速重建",
        "status": "enabled",
        "output": "geometry",
        "profiles": [
            {"id": "recommended", "name": "推荐", "options": {}},
        ],
        "options": {
            "seed": {"type": "integer", "default": 42, "minimum": 0, "maximum": 4294967295},
        },
    },
]


def capability_document() -> dict:
    return {
        "contract": CONTRACT,
        "provider": "modal-3d",
        "kind": "asset3d.generate",
        "operation": OPERATION,
        "outputs": [{"role": OUTPUT_ROLE, "mediaType": OUTPUT_MIME}],
        "generation": {
            "job_transport": JOB_TRANSPORT,
            "entrypoint": "direct_class_method",
            "input_path_prefix": CLIENT_INPUT_PREFIX,
            "artifact_volume": "modal-gen-artifacts",
            "artifact_path_field": "path",
            "input_contract": {
                "role": "canonical_rgba",
                "mime": "image/png",
                "mode": "RGBA",
                "width": CANONICAL_SIZE,
                "height": CANONICAL_SIZE,
                "bit_depth": 8,
                "layout": "letterbox",
                "alpha": "channel_required",
            },
        },
        "models": [
            {
                **dict(m),
                "generation_entrypoint": {
                    "kind": "class_method",
                    "class_name": "Model",
                    "method_name": "generate_job",
                },
            }
            for m in _MODELS
        ],
    }


def _minimal_glb(seed: bytes) -> bytes:
    """Return a small but standards-compliant GLB that Three.js can render."""

    scale = 0.7 + ((seed[0] if seed else 0) / 255.0) * 0.3
    positions = (
        (-scale, -scale, scale),
        (scale, -scale, scale),
        (0.0, scale, 0.0),
        (0.0, -scale, -scale),
    )
    indices = (0, 1, 2, 1, 3, 2, 3, 0, 2, 0, 3, 1)
    binary = b"".join(struct.pack("<3f", *row) for row in positions)
    binary += struct.pack("<12H", *indices)

    document = {
        "asset": {"version": "2.0", "generator": "modal-3d-client-demo"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "material": 0,
                    }
                ]
            }
        ],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.35, 0.58, 0.9, 1.0],
                    "metallicFactor": 0.15,
                    "roughnessFactor": 0.55,
                }
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 48, "target": 34962},
            {"buffer": 0, "byteOffset": 48, "byteLength": 24, "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 4,
                "type": "VEC3",
                "min": [-scale, -scale, -scale],
                "max": [scale, scale, scale],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": 12,
                "type": "SCALAR",
                "min": [0],
                "max": [3],
            },
        ],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)

    body = (
        struct.pack("<I4s", len(json_chunk), b"JSON")
        + json_chunk
        + struct.pack("<I4s", len(binary), b"BIN\x00")
        + binary
    )
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


@dataclass
class _Job:
    id: str
    model: str
    profile: str
    seed: int
    input_sha256: str
    status: str = "running"
    created_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    updated_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    result: dict | None = None
    error_code: str | None = None
    retryable: bool | None = None

    def public(self) -> dict:
        return {
            "id": self.id,
            "model": self.model,
            "profile": self.profile,
            "seed": self.seed,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error_code": self.error_code,
            "retryable": self.retryable,
        }


class _DemoOperationService:
    """In-memory operation transport for offline Asset Contract/UI smoke tests."""

    def __init__(self, jobs: DemoJobService) -> None:
        self.jobs = jobs
        self._jobs: dict[str, dict] = {}
        self._assets: dict[str, dict] = {}
        self._bytes: dict[str, bytes] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _public(state: dict) -> dict:
        return json.loads(json.dumps(state))

    def _register_bytes(self, data: bytes, *, mime: str, role: str, filename: str) -> dict:
        digest = hashlib.sha256(data).hexdigest()
        descriptor = {
            "id": f"art_{digest}",
            "sha256": digest,
            "bytes": len(data),
            "mime": mime,
            "role": role,
            "filename": filename,
        }
        with self._lock:
            self._assets[descriptor["id"]] = descriptor
            self._bytes[descriptor["id"]] = data
        return dict(descriptor)

    def upload(
        self,
        data: bytes,
        *,
        expected_sha256: str | None = None,
        mime: str = "model/gltf-binary",
        role: str = "primary-glb",
        filename: str | None = None,
    ) -> dict:
        if not data or len(data) > MAX_BYTES:
            raise ValueError("artifact must be between 1 byte and 512 MiB")
        suffix_by_mime = {value: suffix for suffix, value in MIMES.items()}
        if mime not in suffix_by_mime:
            raise ValueError(f"unsupported artifact MIME: {mime}")
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError("artifact SHA256 mismatch")
        suffix = suffix_by_mime[mime]
        return self._register_bytes(
            data,
            mime=mime,
            role=role,
            filename=filename or f"input{suffix}",
        )

    def _resolve_ref(self, ref: dict) -> tuple[dict, bytes]:
        if set(ref) == {"artifact_id"}:
            artifact_id = ref["artifact_id"]
            with self._lock:
                descriptor = self._assets.get(artifact_id)
                data = self._bytes.get(artifact_id)
            if descriptor is None or data is None:
                raise KeyError(artifact_id)
            return dict(descriptor), data
        if set(ref) <= {"job_id", "role"} and ref.get("job_id") and ref.get("role"):
            descriptor, path = self.jobs.artifact(ref["job_id"], ref["role"])
            return dict(descriptor), path.read_bytes()
        raise ValueError("invalid artifact reference")

    def submit(self, operation: str, inputs: dict, options=None, job_id: str | None = None) -> dict:
        if operation not in SPECS:
            raise ValueError(f"unsupported operation: {operation}")
        normalized_options = options_for(operation, options)
        if not isinstance(inputs, dict) or set(inputs) != set(SPECS[operation]["inputs"]):
            raise ValueError("inputs do not match operation")

        expected_mimes = input_mimes_for(operation)
        dependencies: list[str] = []
        for name, ref in inputs.items():
            if not isinstance(ref, dict):
                raise TypeError("input must reference artifact_id or job_id + role")
            descriptor, _ = self._resolve_ref(ref)
            if descriptor["mime"] != expected_mimes[name]:
                raise ValueError(f"{name} must be {expected_mimes[name]}")
            if ref.get("job_id"):
                dependencies.append(ref["job_id"])

        local_id = job_id or f"op_{uuid.uuid4().hex}"
        if not local_id.startswith("op_"):
            raise ValueError("operation job_id must start with op_")
        now = self._now()
        state = {
            "id": local_id,
            "operation": operation,
            "model": operation,
            "status": "running",
            "inputs": inputs,
            "options": normalized_options,
            "dependencies": sorted(set(dependencies)),
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error_code": None,
            "retryable": False,
        }
        with self._lock:
            existing = self._jobs.get(local_id)
            if existing is not None:
                if (
                    existing["operation"] != operation
                    or existing["inputs"] != inputs
                    or existing["options"] != normalized_options
                ):
                    raise ValueError("job_id already used with different inputs/options")
                return self._public(existing)
            self._jobs[local_id] = state
        threading.Timer(0.15, self._complete, args=(local_id,)).start()
        return self._public(state)

    def _complete(self, job_id: str) -> None:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None or state["status"] == "cancelled":
                return
            operation = state["operation"]
            inputs = dict(state["inputs"])

        source_ref = inputs.get("asset") or next(iter(inputs.values()))
        _, source_bytes = self._resolve_ref(source_ref)
        glb = source_bytes if source_bytes.startswith(b"glTF") else _minimal_glb(source_bytes[:24])
        artifacts: list[dict] = []
        for role in required_roles_for(operation):
            if role == "primary-glb":
                data = glb
                mime = "model/gltf-binary"
                filename = f"{operation}-{job_id}.glb"
            else:
                data = json.dumps(
                    {"demo": True, "operation": operation, "job_id": job_id, "role": role},
                    sort_keys=True,
                ).encode("utf-8")
                mime = "application/json"
                filename = f"{role}.json"
            artifacts.append(
                self._register_bytes(data, mime=mime, role=role, filename=filename)
            )

        with self._lock:
            state = self._jobs.get(job_id)
            if state is None or state["status"] == "cancelled":
                return
            state["status"] = "succeeded"
            state["updated_at"] = self._now()
            state["result"] = {
                "artifacts": artifacts,
                "metrics": {"demo": True},
                "timing": {"total_s": 0.15},
            }

    def poll(self, job_id: str) -> dict:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            return self._public(state)

    def list(self, limit: int = 50) -> list[dict]:
        with self._lock:
            states = sorted(
                self._jobs.values(), key=lambda row: row["created_at"], reverse=True
            )
            return [self._public(row) for row in states[:limit]]

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            if state["status"] != "succeeded":
                state["status"] = "cancelled"
                state["updated_at"] = self._now()
            return self._public(state)

    def artifact(self, job_id: str, role: str = "primary-glb") -> tuple[dict, Path]:
        state = self.poll(job_id)
        if state["status"] != "succeeded" or not state.get("result"):
            raise RuntimeError("job artifact is not ready")
        descriptor = next(
            (
                row
                for row in state["result"]["artifacts"]
                if row["role"] == role or row["id"] == role
            ),
            None,
        )
        if descriptor is None:
            raise KeyError(role)
        data = self._bytes[descriptor["id"]]
        suffix = {value: key for key, value in MIMES.items()}[descriptor["mime"]]
        path = self.jobs._tmpdir / f"{job_id}-{descriptor['role']}{suffix}"
        path.write_bytes(data)
        return dict(descriptor), path


class DemoJobService:
    """Drop-in replacement for ``jobs.JobService`` used by the demo app."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, _Job] = {}
        self._artifacts: dict[str, bytes] = {}
        self._tmpdir = Path(tempfile.mkdtemp(prefix="modal-3d-demo-"))
        self.store = _DemoStore(self)
        self.operations = _DemoOperationService(self)

    def submit(
        self,
        source_image: bytes,
        *,
        model: str,
        profile: str,
        seed: int,
        job_id: str | None = None,
        mask: bytes | None = None,
    ) -> dict:
        local_id = job_id or f"job_{uuid.uuid4().hex}"
        sha = hashlib.sha256(source_image).hexdigest()
        with self._lock:
            existing = self._jobs.get(local_id)
            if existing is not None:
                return existing.public()
            job = _Job(
                id=local_id,
                model=model,
                profile=profile,
                seed=seed,
                input_sha256=sha,
            )
            self._jobs[local_id] = job
        # Simulate an async transition so the UI exercises running -> succeeded.
        threading.Timer(0.6, self._complete, args=(local_id, sha)).start()
        return job.public()

    def _complete(self, job_id: str, sha: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in {"cancel_requested", "cancelled"}:
                return
            glb = _minimal_glb(sha.encode()[:24])
            artifact_sha = hashlib.sha256(glb).hexdigest()
            self._artifacts[job_id] = glb
            job.status = "succeeded"
            job.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            job.result = {
                "artifact": {
                    "id": f"art_{artifact_sha[:16]}",
                    "role": OUTPUT_ROLE,
                    "mediaType": OUTPUT_MIME,
                    "mime": OUTPUT_MIME,
                    "sha256": artifact_sha,
                    "bytes": len(glb),
                },
                "conditioning": {
                    "strategy": "birefnet",
                    "engine": "birefnet-general-lite",
                    "source_sha256": sha,
                    "foreground_ratio": 0.28,
                },
            }
            job.retryable = False

    def poll(self, job_id: str) -> dict:
        if job_id.startswith("op_"):
            return self.operations.poll(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return job.public()

    def cancel(self, job_id: str) -> dict:
        if job_id.startswith("op_"):
            return self.operations.cancel(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            job.status = "cancelled"
            job.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            job.retryable = False
            return job.public()

    def artifact(self, job_id: str, role: str = "primary-glb") -> tuple[dict, Path]:
        if job_id.startswith("op_"):
            return self.operations.artifact(job_id, role)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status != "succeeded" or not job.result:
                raise RuntimeError("job artifact is not ready")
            descriptor = dict(job.result["artifact"])
            glb = self._artifacts.get(job_id)
        if glb is None:
            raise FileNotFoundError("artifact not found")
        path = self._tmpdir / f"{job_id}.glb"
        path.write_bytes(glb)
        return descriptor, path


class _DemoStore:
    def __init__(self, service: DemoJobService) -> None:
        self._service = service

    def list(self, limit: int = 50) -> list[dict]:
        with self._service._lock:
            jobs = sorted(self._service._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.public() for j in jobs[:limit]]
