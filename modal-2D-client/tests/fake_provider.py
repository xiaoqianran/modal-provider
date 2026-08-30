"""为 UI 渲染验证提供可用的假后端。

目的：在不连接 Modal 的前提下，让操作台的所有状态都能真实走通一遍——
connected / capabilities / models / 非终态 Job / 终态 Job / 二进制产物。

只用于 `python -m modal_2d_client.dev_stub` 本地起服务做截图与交互核查，
不参与 pytest，也不被生产代码引用。
"""

from __future__ import annotations

import hashlib
import io
import struct
import time
import zlib
from pathlib import Path

PNG_SIZE = 1024


def make_png(seed: int = 0) -> bytes:
    """生成一个真实可解码的 1024×1024 灰度 PNG。"""
    rows = bytearray()
    for y in range(PNG_SIZE):
        rows.append(0)  # filter type 0
        value = (y * 255 // (PNG_SIZE - 1) + seed) % 256
        rows.extend(bytes([value]) * PNG_SIZE)

    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))

    ihdr = struct.pack(">IIBBBBB", PNG_SIZE, PNG_SIZE, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )


def png_bytes_io(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeCapabilities:
    """替代 modal_2d_client.capabilities，不触网。"""

    DOC = {
        "contract": "modal-2d.generation.v2",
        "provider": "modal-2d",
        "kind": "image.generate",
        "operation": "modal-2d.image.text_to_image.v1",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["prompt"],
            "properties": {
                "prompt": {"type": "string", "minLength": 1, "maxLength": 4000},
                "model": {"type": "string", "enum": ["sana-sprint-1.6b", "sana-sprint-0.6b"]},
                "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295},
                "guidance": {"type": "number", "minimum": 0.0, "maximum": 20.0},
            },
        },
        "outputs": [{"role": "primary-image", "mediaType": "image/png"}],
        "execution": {"mode": "async", "cancellable": True},
        "generation": {
            "control_app": "modal-2d",
            "prefetch_function": "prefetch",
            "batch_max_size": 8,
            "artifact_function": "read_artifact",
            "artifact_volume": "modal-gen-artifacts",
            "artifact_path_field": "remote_path",
            "job_transport": "modal.FunctionCall",
        },
        "input": {"prompt": {"type": "string"}, "size": {"width": 1024, "height": 1024}},
        "artifact": {
            "role": "primary-image",
            "mime": "image/png",
            "format": "png",
            "lossless": True,
        },
        "models": [
            {
                "id": "sana-sprint-1.6b",
                "name": "SANA-Sprint 1.6B",
                "hf_id": "Efficient-Large-Model/Sana_Sprint_1.6B_1024px_diffusers",
                "parameters": "1.6B",
                "steps": 2,
                "guidance": 4.5,
                "width": 1024,
                "height": 1024,
                "profiles": [{"id": "recommended", "steps": 2, "guidance": 4.5}],
                "generation_entrypoint": {
                    "app": "modal-2d-sana-sprint",
                    "class_name": "Model",
                    "generate_method": "generate",
                    "batch_generate_method": "generate_batch",
                },
            },
            {
                "id": "sana-sprint-0.6b",
                "name": "SANA-Sprint 0.6B",
                "hf_id": "Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers",
                "parameters": "0.6B",
                "steps": 2,
                "guidance": 4.5,
                "width": 1024,
                "height": 1024,
                "profiles": [{"id": "recommended", "steps": 2, "guidance": 4.5}],
                "generation_entrypoint": {
                    "app": "modal-2d-sana-sprint",
                    "class_name": "Model",
                    "generate_method": "generate",
                    "batch_generate_method": "generate_batch",
                },
            },
        ],
    }

    @staticmethod
    def document(*, refresh_remote: bool = True) -> dict:
        return FakeCapabilities.DOC

    @staticmethod
    def refresh() -> dict:
        return FakeCapabilities.DOC

    @staticmethod
    def public_models() -> list[dict]:
        return [
            {
                "id": m["id"],
                "name": m["name"],
                "parameters": m.get("parameters"),
                "profiles": m["profiles"],
                "width": m["width"],
                "height": m["height"],
            }
            for m in FakeCapabilities.DOC["models"]
        ]

    @staticmethod
    def ensure_model(model_id: str) -> None:
        if model_id not in {m["id"] for m in FakeCapabilities.DOC["models"]}:
            raise ValueError(f"unsupported model: {model_id}")


class FakeModalSession:
    """替代 modal_2d_client.modal_session，不触碰真实 Modal。"""

    connected = True

    class NotConnectedError(RuntimeError):
        pass

    @staticmethod
    def connect(token_id: str, token_secret: str) -> None:
        if not token_id or not token_secret:
            raise ValueError("Modal credentials are required")
        FakeModalSession.connected = True

    @staticmethod
    def disconnect() -> None:
        FakeModalSession.connected = False

    @staticmethod
    def client():
        raise RuntimeError("dev stub 不连接 Modal")


class FakeArtifacts:
    """把产物落到一个可预测的临时目录，模拟 Volume-first 落盘。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def fetch(self, descriptor: dict) -> Path:
        data = make_png(int(str(descriptor.get("id", "0"))[-1] or 0))
        path = self.root / f"{descriptor['id']}.png"
        path.write_bytes(data)
        return path


class FakeJobService:
    """内存版 JobService：提交后按时间推进到终态，便于观察轮询行为。

    未连接时提交会像真实 JobService 一样抛 NotConnectedError，
    以便 UI 的 409 分支能被真实走到。
    """

    def __init__(self, artifacts: FakeArtifacts) -> None:
        self.artifacts = artifacts
        self.store = self
        self._jobs: dict[str, dict] = {}
        self._seed_jobs()

    # -- store 接口（供 /v1/jobs 列表） --------------------------------
    def list(self, limit: int = 50) -> list[dict]:
        rows = sorted(self._jobs.values(), key=lambda j: j["created_at"], reverse=True)
        return [dict(row) for row in rows[:limit]]

    # -- service 接口 --------------------------------------------------
    def submit(self, payload: dict, *, job_id: str | None = None) -> dict:
        if not FakeModalSession.connected:
            raise FakeModalSession.NotConnectedError("Modal 尚未连接")
        local_id = job_id or f"job_{len(self._jobs):03d}"
        now = time.time()
        self._jobs[local_id] = {
            "id": local_id,
            "model": payload.get("model", "sana-sprint-1.6b"),
            "remote_call_id": f"fc-{local_id}",
            "status": "running",
            "created_at": self._iso(now),
            "updated_at": self._iso(now),
            "result": None,
            "error_code": None,
            "retryable": True,
            "_payload": payload,
            "_started": now,
            "_after": 3.0,
        }
        return dict(self._jobs[local_id])

    def poll(self, job_id: str) -> dict:
        job = self._get(job_id)
        if job["status"] not in ("succeeded", "failed", "cancelled", "expired"):
            if time.time() - job["_started"] >= job["_after"]:
                job["result"] = self._result(job)
                job["status"] = "succeeded"
                job["updated_at"] = self._iso()
                job["retryable"] = False
        return self._public(job)

    def cancel(self, job_id: str) -> dict:
        job = self._get(job_id)
        if job["status"] not in ("succeeded", "failed", "cancelled", "expired"):
            job["status"] = "cancel_requested"
            job["updated_at"] = self._iso()
        return self._public(job)

    def artifact(self, job_id: str, index: int | None = None) -> tuple[dict, Path]:
        job = self._get(job_id)
        state = self.poll(job_id)
        if state["status"] != "succeeded":
            raise RuntimeError("job artifact is not ready")
        result = job["result"]
        if "artifacts" in result:
            if index is None:
                raise RuntimeError("batch job requires an artifact index")
            descriptor = result["artifacts"][index]
        else:
            descriptor = result["artifact"]
        return descriptor, self.artifacts.fetch(descriptor)

    # -- 内部 ----------------------------------------------------------
    def _get(self, job_id: str) -> dict:
        if job_id not in self._jobs:
            raise KeyError(job_id)
        return self._jobs[job_id]

    def _public(self, job: dict) -> dict:
        return {
            "id": job["id"],
            "model": job["model"],
            "status": job["status"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "result": job["result"],
            "error_code": job["error_code"],
            "retryable": job["retryable"],
        }

    def _result(self, job: dict) -> dict:
        seeds = job["_payload"].get("seeds") or [job["_payload"].get("seed", 42)]
        descriptors = [self._descriptor(seed) for seed in seeds]
        if len(descriptors) == 1:
            return {"artifact": descriptors[0]}
        return {
            "artifacts": descriptors,
            "timing": {
                "worker_reused": True,
                "worker_load_ms": None,
                "batch_total_ms": 9075.0,
                "items": [
                    {
                        "seed": seed,
                        "inference_ms": 1352.0,
                        "artifact_write_ms": 12.5,
                        "total_ms": 1364.5,
                    }
                    for seed in seeds
                ],
            },
        }

    def _descriptor(self, seed: int) -> dict:
        data = make_png(seed % 256)
        digest = sha256_hex(data)
        artifact_id = f"art_{abs(hash((seed, digest[:8]))) % 10**12:012d}"
        return {
            "id": artifact_id,
            "role": "primary-image",
            "mediaType": "image/png",
            "digest": f"sha256:{digest}",
            "producer": {
                "provider": "modal-2d",
                "operation": "modal-2d.image.text_to_image.v1",
            },
            "mime": "image/png",
            "format": "png",
            "bytes": len(data),
            "sha256": digest,
            "width": 1024,
            "height": 1024,
            "remote_path": f"sources/sha256/{digest[:2]}/{digest}",
        }

    def _seed_jobs(self) -> None:
        """预置几个 Job，让列表/状态徽章一进页面就有真实内容可审。"""
        now = time.time()
        presets = [
            (
                "job_seed_done",
                "sana-sprint-1.6b",
                {"prompt": "a glossy red apple", "seeds": [42, 73, 104, 135]},
                "succeeded",
                -120,
            ),
            (
                "job_seed_single",
                "sana-sprint-1.6b",
                {"prompt": "mossy stone house", "seed": 7},
                "succeeded",
                -60,
            ),
            (
                "job_seed_failed",
                "sana-sprint-0.6b",
                {"prompt": "broken prompt", "seed": 3},
                "failed",
                -30,
            ),
        ]
        for job_id, model, payload, status, offset in presets:
            self._jobs[job_id] = {
                "id": job_id,
                "model": model,
                "remote_call_id": f"fc-{job_id}",
                "status": "running",
                "created_at": self._iso(now + offset),
                "updated_at": self._iso(now + offset),
                "result": None,
                "error_code": None,
                "retryable": True,
                "_payload": payload,
                "_started": now + offset,
                "_after": 0,
            }
            job = self._jobs[job_id]
            if status == "succeeded":
                job["result"] = self._result(job)
                job["status"] = "succeeded"
                job["retryable"] = False
            elif status == "failed":
                job["status"] = "failed"
                job["error_code"] = "remote.execution_failed"
                job["retryable"] = False

    @staticmethod
    def _iso(ts: float | None = None) -> str:
        from datetime import UTC, datetime

        moment = datetime.fromtimestamp(ts if ts is not None else time.time(), UTC)
        return moment.isoformat()
