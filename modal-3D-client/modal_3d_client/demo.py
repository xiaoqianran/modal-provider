from __future__ import annotations

"""Offline demo provider.

When ``MODAL_3D_CLIENT_DEMO=1`` the sidecar advertises a fake capability
document and resolves every job through an in-memory store, so the bundled web
UI can be exercised end-to-end without a Modal account or a deployed worker.
This is a development affordance only; it never touches the Modal SDK.
"""

import hashlib
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

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
            "artifact_volume": "modal-3d-artifacts",
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
    body = seed + b"\x00" * 40
    total = 12 + len(body)
    return b"glTF" + (2).to_bytes(4, "little") + total.to_bytes(4, "little") + body


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


class DemoJobService:
    """Drop-in replacement for ``jobs.JobService`` used by the demo app."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, _Job] = {}
        self._artifacts: dict[str, bytes] = {}
        self._tmpdir = Path(tempfile.mkdtemp(prefix="modal-3d-demo-"))
        self.store = _DemoStore(self)

    def submit(
        self,
        source_image: bytes,
        *,
        model: str,
        profile: str,
        seed: int,
        job_id: str | None = None,
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
            artifact_sha = hashlib.sha256(sha.encode()).hexdigest()
            glb = _minimal_glb(artifact_sha.encode()[:24])
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
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return job.public()

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            job.status = "cancelled"
            job.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            job.retryable = False
            return job.public()

    def artifact(self, job_id: str) -> tuple[dict, Path]:
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
