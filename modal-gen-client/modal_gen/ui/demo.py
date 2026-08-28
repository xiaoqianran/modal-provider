"""Demo backend for the local console UI.

This engine exists ONLY so the console UI can be rendered, screenshotted and
reviewed when no real Connector providers are reachable. It mirrors the real
connector contract shapes (provider descriptors, jobs, artifacts) but never
impersonates a Provider Agent. In live mode it is not used at all.
"""

from __future__ import annotations

import json
import struct
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any

_CLIENT = "agentscape"
_ORIGIN = "http://127.0.0.1:48124"
_CONNECTOR_ID = "unified-connector"
_CONNECTOR_VERSION = "0.1.0"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Synthetic artifacts (real bytes so download/hash verification is honest)
# --------------------------------------------------------------------------- #
def make_png(width: int, height: int, seed: int = 7) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # PNG filter type 0
        for x in range(width):
            r = min(255, (x * 255) // width)
            g = min(255, (y * 255) // height)
            b = (x * 31 + y * 17 + seed * 53) % 256
            raw += bytes((r, g, b, 255))
    body = bytes(raw)

    def chunk(tag: bytes, data: bytes) -> bytes:
        block = tag + data
        return (
            struct.pack(">I", len(data)) + block + struct.pack(">I", zlib.crc32(block) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(body, 9))
        + chunk(b"IEND", b"")
    )
    return png


def make_glb() -> bytes:
    positions = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    indices = [0, 1, 2]
    bin_data = struct.pack("<9f", *positions) + struct.pack("<3H", *indices)
    bin_data += b"\x00\x00"  # pad to 4-byte boundary
    vertex_min = [0.0, 0.0, 0.0]
    vertex_max = [1.0, 1.0, 0.0]
    gltf = {
        "asset": {"version": "2.0", "generator": "modal-gen-client demo"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.81, 0.5, 0.2, 1.0],
                    "metallicFactor": 0.1,
                    "roughnessFactor": 0.6,
                },
                "name": "demo-surface",
            }
        ],
        "buffers": [{"byteLength": len(bin_data)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36, "target": 34962},
            {"buffer": 0, "byteOffset": 36, "byteLength": 6, "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 6,
                "type": "VEC3",
                "min": vertex_min,
                "max": vertex_max,
            },
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    if len(json_bytes) % 4:
        json_bytes += b" " * (4 - len(json_bytes) % 4)
    glb = bytearray()
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_data)
    glb += struct.pack("<4sII", b"glTF", 2, total)
    glb += struct.pack("<I4s", len(json_bytes), b"JSON")
    glb += json_bytes
    glb += struct.pack("<I4s", len(bin_data), b"BIN\x00")
    glb += bin_data
    return bytes(glb)


def _sha256_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# Capability fixtures (shapes taken from the connector contract, not from UI)
# --------------------------------------------------------------------------- #
def _provider_2d() -> dict[str, Any]:
    return {
        "id": "modal-2d",
        "displayName": "Modal 2D",
        "version": "1",
        "implementationRevision": "sana-sprint-v1",
        "health": "healthy",
        "status": "available",
        "contractVersion": "1",
        "artifactTransport": "connector-artifact",
        "capabilities": [
            {
                "operation": "modal-2d.image.text_to_image.v1",
                "version": "1",
                "displayName": "SANA-Sprint Text to Image",
                "category": "image-generation",
                "status": "available",
                "input": {
                    "types": ["text"],
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["prompt"],
                        "properties": {
                            "prompt": {"type": "string", "minLength": 1, "maxLength": 4000},
                            "model": {
                                "type": "string",
                                "enum": ["sana-sprint-0.6b", "sana-sprint-1.6b"],
                            },
                            "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295},
                            "guidance": {"type": "number", "minimum": 0, "maximum": 20},
                        },
                    },
                    "limits": {"width": 1024, "height": 1024, "steps": 2},
                },
                "output": {
                    "roles": ["primary-image"],
                    "required": ["primary-image"],
                    "optional": [],
                },
                "profiles": {"recommended": {"steps": 2, "guidance": 4.5}},
                "optionsSchema": {"type": "object", "additionalProperties": False},
                "execution": {
                    "async": True,
                    "stages": ["queued", "running", "artifact"],
                    "durationClass": "medium",
                    "costClass": "gpu",
                },
                "prerequisites": {"authMode": "connector-session", "connection": True},
                "support": {"cancel": True, "resume": True, "idempotency": True},
                "artifactTransport": "connector-artifact",
            }
        ],
    }


def _provider_3d(unavailable: bool = False) -> dict[str, Any]:
    status = "disabled" if unavailable else "available"
    health = "unavailable" if unavailable else "healthy"
    models = (
        []
        if unavailable
        else [
            {"id": "fastsam3d-plus-plus", "status": "enabled", "profile_ids": ["recommended"]},
            {"id": "hunyuan2-1-plus-plus", "status": "enabled", "profile_ids": ["recommended"]},
            {"id": "trellis2-plus-plus", "status": "degraded", "profile_ids": ["recommended"]},
        ]
    )
    return {
        "id": "modal-3d",
        "displayName": "Modal 3D",
        "version": "1",
        "implementationRevision": "demo-asset-capabilities",
        "health": health,
        "status": status,
        "contractVersion": "1",
        "artifactTransport": "connector-artifact",
        "capabilities": [
            {
                "operation": "modal-3d.asset.image_to_3d.v1",
                "version": "1",
                "displayName": "Image to 3D",
                "category": "asset-generation",
                "status": status,
                "input": {
                    "types": ["image"],
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["sourceArtifact", "model"],
                        "properties": {
                            "sourceArtifact": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string", "minLength": 1},
                                    "role": {"const": "primary-image"},
                                    "mime": {"const": "image/png"},
                                    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                                },
                            },
                            "model": {
                                "type": "string",
                                "enum": [m["id"] for m in models],
                            },
                            "seed": {"type": "integer", "default": 42},
                        },
                    },
                    "limits": {"maxSourceBytes": 20971520},
                },
                "output": {
                    "roles": ["primary-glb"],
                    "required": ["primary-glb"],
                    "optional": [],
                },
                "profiles": {"recommended": {}},
                "optionsSchema": {"type": "object", "additionalProperties": False},
                "execution": {
                    "async": True,
                    "stages": ["source", "preprocess", "generation", "artifact"],
                    "durationClass": "long",
                    "costClass": "gpu",
                },
                "prerequisites": {"authMode": "connector-session", "connection": True},
                "support": {"cancel": True, "resume": True, "idempotency": True},
                "artifactTransport": "connector-artifact",
            }
        ],
    }


def build_capability_snapshot(*, three_d_unavailable: bool = False) -> dict[str, Any]:
    providers = [_provider_2d(), _provider_3d(three_d_unavailable)]
    canonical = {
        "contractVersion": "1",
        "connector": {
            "id": _CONNECTOR_ID,
            "instance": "demo-instance",
            "version": _CONNECTOR_VERSION,
        },
        "providers": providers,
    }
    digest = _sha256_hex(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode())
    return {
        **canonical,
        "revision": f"caprev_{digest[:24]}",
        "hash": f"sha256:{digest}",
        "generatedAt": _iso(_now()),
        "expiresAt": _iso(_now() + timedelta(minutes=30)),
        "cachePolicy": {"maxAgeSeconds": 60},
    }


# --------------------------------------------------------------------------- #
# Job + artifact lifecycle
# --------------------------------------------------------------------------- #
class DemoEngine:
    """In-memory connector double for offline rendering."""

    def __init__(self) -> None:
        self.snapshot = build_capability_snapshot()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.artifacts: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self._seed_jobs()

    # -- bootstrap ---------------------------------------------------------- #
    def session_descriptor(self) -> dict[str, Any]:
        return {
            "clientIdentity": _CLIENT,
            "contractVersion": "1",
            "origin": _ORIGIN,
            "scopes": [
                "capabilities.read",
                "jobs.submit",
                "jobs.read",
                "jobs.cancel",
                "artifacts.read",
            ],
            "issuedAt": _iso(_now()),
            "expiresAt": _iso(_now() + timedelta(minutes=15)),
            "allowedOrigins": [_ORIGIN],
            "capabilityRevision": self.snapshot["revision"],
            "capabilityHash": self.snapshot["hash"],
            "revokeEndpoint": "/connector/v1/session",
        }

    def capabilities(self) -> dict[str, Any]:
        return self.snapshot

    def list_pairings(self) -> list[dict[str, Any]]:
        return []

    def list_jobs(
        self, *, status: str | None = None, q: str = "", page: int = 1, page_size: int = 25
    ):
        rows = list(self.jobs.values())
        rows.sort(key=lambda r: r.get("createdAt") or "", reverse=True)
        if status and status != "all":
            rows = [r for r in rows if r["status"] == status]
        if q:
            needle = q.lower()
            rows = [
                r
                for r in rows
                if needle in r["id"].lower()
                or needle in (r.get("prompt") or "").lower()
                or needle in r["provider"]
            ]
        total = len(rows)
        start = (page - 1) * page_size
        return {"jobs": rows[start : start + page_size], "page": page, "total": total}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def submit_job(self, provider: str, operation: str, inputs: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        job_id = f"job_{self._seq:04d}"
        now = _iso(_now())
        row = {
            "id": job_id,
            "provider": provider,
            "operation": operation,
            "kind": "generation",
            "requestHash": f"sha256:{_sha256_hex(job_id.encode())}",
            "idempotencyKey": f"idem_{job_id}",
            "contractVersion": "1",
            "capabilityHash": self.snapshot["hash"],
            "capabilityRevision": self.snapshot["revision"],
            "status": "accepted",
            "stage": "submitted",
            "attempt": 1,
            "relations": [],
            "effectiveOptions": {},
            "model": {
                "id": str(inputs.get("model") or "demo-model"),
                "version": None,
                "revision": None,
            },
            "createdAt": now,
            "submittedAt": now,
            "startedAt": None,
            "updatedAt": now,
            "completedAt": None,
            "error": None,
            "result": None,
            "eventSequence": 1,
            "prompt": inputs.get("prompt"),
        }
        self.jobs[job_id] = row
        return self._project(row)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        row = self.jobs.get(job_id)
        if not row:
            return None
        if row["status"] in {"succeeded", "failed", "cancelled", "expired"}:
            return self._project(row)
        row["status"] = "cancel_requested"
        row["updatedAt"] = _iso(_now())
        return self._project(row)

    def list_artifacts(self) -> list[dict[str, Any]]:
        return sorted(self.artifacts.values(), key=lambda a: a["id"])

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        return self.artifacts.get(artifact_id)

    def artifact_bytes(self, artifact_id: str) -> bytes | None:
        entry = self.artifacts.get(artifact_id)
        if not entry:
            return None
        return entry["_bytes"]

    # -- internal ----------------------------------------------------------- #
    def _project(self, row: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in row.items() if k != "_bytes"}

    def _seed_jobs(self) -> None:
        now = _now()
        png = make_png(256, 256, 3)

        def mk_artifact(job_id: str, role: str, mime: str, data: bytes) -> str:
            aid = f"artifact_{len(self.artifacts) + 1:04d}"
            self.artifacts[aid] = {
                "id": aid,
                "job_id": job_id,
                "role": role,
                "mime": mime,
                "bytes": len(data),
                "hash": f"sha256:{_sha256_hex(data)}",
                "provider_artifact_id": f"p_{aid}",
                "provider_job_id": job_id,
                "_bytes": data,
            }
            return aid

        # 1) succeeded image job with artifact
        self._seq += 1
        j1 = f"job_{self._seq:04d}"
        self.jobs[j1] = {
            "id": j1,
            "provider": "modal-2d",
            "operation": "modal-2d.image.text_to_image.v1",
            "status": "succeeded",
            "stage": "artifact",
            "attempt": 1,
            "createdAt": _iso(now - timedelta(minutes=42)),
            "submittedAt": _iso(now - timedelta(minutes=42)),
            "startedAt": _iso(now - timedelta(minutes=41, seconds=30)),
            "updatedAt": _iso(now - timedelta(minutes=40)),
            "completedAt": _iso(now - timedelta(minutes=40)),
            "model": {"id": "sana-sprint-1.6b"},
            "prompt": "a glossy red apple on a marble counter, soft studio light",
            "result": {},
            "error": None,
            "eventSequence": 6,
        }
        mk_artifact(j1, "primary-image", "image/png", png)

        # 2) running job
        self._seq += 1
        j2 = f"job_{self._seq:04d}"
        self.jobs[j2] = {
            "id": j2,
            "provider": "modal-3d",
            "operation": "modal-3d.asset.image_to_3d.v1",
            "status": "running",
            "stage": "generation",
            "attempt": 1,
            "createdAt": _iso(now - timedelta(minutes=6)),
            "submittedAt": _iso(now - timedelta(minutes=6)),
            "startedAt": _iso(now - timedelta(minutes=5)),
            "updatedAt": _iso(now - timedelta(seconds=20)),
            "completedAt": None,
            "model": {"id": "fastsam3d-plus-plus"},
            "result": {},
            "error": None,
            "eventSequence": 4,
        }

        # 3) failed job
        self._seq += 1
        j3 = f"job_{self._seq:04d}"
        self.jobs[j3] = {
            "id": j3,
            "provider": "modal-2d",
            "operation": "modal-2d.image.text_to_image.v1",
            "status": "failed",
            "stage": "failed",
            "attempt": 1,
            "createdAt": _iso(now - timedelta(minutes=18)),
            "submittedAt": _iso(now - timedelta(minutes=18)),
            "startedAt": _iso(now - timedelta(minutes=17)),
            "updatedAt": _iso(now - timedelta(minutes=16)),
            "completedAt": _iso(now - timedelta(minutes=16)),
            "model": {"id": "sana-sprint-0.6b"},
            "prompt": "a violet crystal chandelier floating in zero gravity",
            "result": {},
            "error": {"code": "PROVIDER_REQUEST_REJECTED", "retryable": True},
            "eventSequence": 5,
        }

        # 4) connection_required (recoverable) job
        self._seq += 1
        j4 = f"job_{self._seq:04d}"
        self.jobs[j4] = {
            "id": j4,
            "provider": "modal-3d",
            "operation": "modal-3d.asset.image_to_3d.v1",
            "status": "connection_required",
            "stage": "connection",
            "attempt": 1,
            "createdAt": _iso(now - timedelta(minutes=2)),
            "submittedAt": _iso(now - timedelta(minutes=2)),
            "startedAt": None,
            "updatedAt": _iso(now - timedelta(seconds=30)),
            "completedAt": None,
            "model": {"id": "trellis2-plus-plus"},
            "result": {},
            "error": {"code": "PROVIDER_CONNECTION_REQUIRED", "recoverable": True},
            "eventSequence": 2,
        }

        # 5) cancelled job
        self._seq += 1
        j5 = f"job_{self._seq:04d}"
        self.jobs[j5] = {
            "id": j5,
            "provider": "modal-2d",
            "operation": "modal-2d.image.text_to_image.v1",
            "status": "cancelled",
            "stage": "cancelled",
            "attempt": 1,
            "createdAt": _iso(now - timedelta(minutes=70)),
            "submittedAt": _iso(now - timedelta(minutes=70)),
            "startedAt": _iso(now - timedelta(minutes=69)),
            "updatedAt": _iso(now - timedelta(minutes=68)),
            "completedAt": _iso(now - timedelta(minutes=68)),
            "model": {"id": "sana-sprint-1.6b"},
            "prompt": (
                "long prompt that should overflow the table cell on purpose to test "
                "truncation and wrapping behaviour across the row display"
            ),
            "result": {},
            "error": None,
            "eventSequence": 4,
        }


def write_sample_artifact(path: str) -> None:
    data = make_png(64, 64, 11)
    with open(path, "wb") as stream:
        stream.write(data)
