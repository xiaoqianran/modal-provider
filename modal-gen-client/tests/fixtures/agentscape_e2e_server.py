from __future__ import annotations

import argparse
import base64
import hashlib
import shutil
from pathlib import Path

import uvicorn
from modal_2d_client.provider import Modal2DProvider
from modal_3d_client.provider import Modal3DProvider

from modal_gen.app import build_runtime, create_app
from modal_gen.providers.loader import adapt_providers
from modal_gen.storage import Store

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+XwJtWQAAAABJRU5ErkJggg=="
)


class Deterministic2DJobs:
    def __init__(self, root: Path) -> None:
        self.path = root / "cup.png"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(PNG)
        self.descriptor = {
            "id": "provider_cup_image",
            "role": "primary-image",
            "mime": "image/png",
            "bytes": len(PNG),
            "sha256": hashlib.sha256(PNG).hexdigest(),
            "width": 1,
            "height": 1,
        }

    def submit(self, payload: dict[str, object], *, job_id: str | None = None) -> dict[str, object]:
        return {
            "id": job_id,
            "model": str(payload.get("model") or "sana-sprint-1.6b"),
            "status": "running",
            "result": None,
            "error_code": None,
            "retryable": True,
        }

    def poll(self, job_id: str) -> dict[str, object]:
        return {
            "id": job_id,
            "model": "sana-sprint-1.6b",
            "status": "succeeded",
            "result": {"artifact": self.descriptor},
            "error_code": None,
            "retryable": False,
        }

    def cancel(self, job_id: str) -> dict[str, object]:
        return {"id": job_id, "model": "sana-sprint-1.6b", "status": "cancel_requested"}

    def artifact(self, _job_id: str, index: int | None = None):
        if index not in (None, 0):
            raise IndexError(index)
        return self.descriptor, self.path


class Deterministic3DJobs:
    def __init__(self, root: Path, glb: Path) -> None:
        self.path = root / "generated-cup.glb"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(glb, self.path)
        data = self.path.read_bytes()
        self.descriptor = {
            "id": "provider_generated_cup",
            "role": "primary-glb",
            "mime": "model/gltf-binary",
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def submit(
        self,
        source_image: bytes,
        *,
        model: str,
        profile: str = "recommended",
        seed: int = 42,
        job_id: str | None = None,
        mask: bytes | None = None,
    ) -> dict[str, object]:
        if source_image != PNG:
            raise ValueError("unexpected deterministic source image")
        if profile != "recommended" or mask is not None:
            raise ValueError("unexpected deterministic 3D options")
        return {
            "id": job_id,
            "model": model,
            "status": "running",
            "result": None,
            "error_code": None,
            "retryable": True,
        }

    def poll(self, job_id: str) -> dict[str, object]:
        return {
            "id": job_id,
            "model": "fastsam3d-plus-plus",
            "status": "succeeded",
            "result": {"artifact": self.descriptor},
            "error_code": None,
            "retryable": False,
        }

    def cancel(self, job_id: str) -> dict[str, object]:
        return {"id": job_id, "model": "fastsam3d-plus-plus", "status": "cancel_requested"}

    def artifact(self, _job_id: str):
        return self.descriptor, self.path


class Deterministic2DProvider(Modal2DProvider):
    def deployment_manifest(self) -> dict[str, object]:
        return {"provider": self.id, "targets": []}


class Deterministic3DProvider(Modal3DProvider):
    def deployment_manifest(self) -> dict[str, object]:
        return {"provider": self.id, "targets": []}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)

    adapters = adapt_providers(
        [
            Deterministic2DProvider(Deterministic2DJobs(args.data_dir)),
            Deterministic3DProvider(Deterministic3DJobs(args.data_dir, args.glb)),
        ]
    )
    runtime = build_runtime(Store(args.data_dir / "connector.sqlite3"), adapters=adapters)
    uvicorn.run(create_app(runtime), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
