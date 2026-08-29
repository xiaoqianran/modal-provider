from __future__ import annotations

import hashlib
from pathlib import Path

from modal_2d_client.provider import Modal2DProvider
from modal_3d_client.provider import Modal3DProvider

from modal_gen.app import build_runtime
from modal_gen.identity import idempotency_key, request_hash
from modal_gen.providers.loader import adapt_providers
from modal_gen.storage import Store
from tests.test_connector_e2e import ORIGIN, PNG, SCOPES, make_request

GLB = b"glTF" + (2).to_bytes(4, "little") + (16).to_bytes(4, "little") + b"data"


class Fake2DJobs:
    def __init__(self, root: Path) -> None:
        self.path = root / "image.png"
        self.path.write_bytes(PNG)
        self.descriptor = {
            "id": "provider_image_01",
            "role": "primary-image",
            "mime": "image/png",
            "format": "png",
            "bytes": len(PNG),
            "sha256": hashlib.sha256(PNG).hexdigest(),
            "width": 1024,
            "height": 1024,
        }

    def submit(self, payload, *, job_id=None):
        return {
            "id": job_id,
            "model": payload.get("model") or "sana-sprint-1.6b",
            "status": "running",
            "result": None,
            "error_code": None,
            "retryable": True,
        }

    def poll(self, job_id):
        return {
            "id": job_id,
            "model": "sana-sprint-1.6b",
            "status": "succeeded",
            "result": {"artifact": self.descriptor},
            "error_code": None,
            "retryable": False,
        }

    def cancel(self, job_id):
        return {"id": job_id, "status": "cancel_requested", "model": "sana-sprint-1.6b"}

    def artifact(self, job_id, index=None):
        assert index in (None, 0)
        return self.descriptor, self.path


class Fake3DJobs:
    def __init__(self, root: Path) -> None:
        self.path = root / "model.glb"
        self.path.write_bytes(GLB)
        self.source: bytes | None = None
        self.descriptor = {
            "id": "provider_glb_01",
            "role": "primary-glb",
            "mime": "model/gltf-binary",
            "bytes": len(GLB),
            "sha256": hashlib.sha256(GLB).hexdigest(),
        }

    def submit(
        self, source_image, *, model, profile="recommended", seed=42, job_id=None, mask=None
    ):
        self.source = source_image
        assert model == "fastsam3d-plus-plus"
        assert profile == "recommended"
        assert seed == 9
        assert mask is None
        return {
            "id": job_id,
            "model": model,
            "status": "running",
            "result": None,
            "error_code": None,
            "retryable": True,
        }

    def poll(self, job_id):
        return {
            "id": job_id,
            "model": "fastsam3d-plus-plus",
            "status": "succeeded",
            "result": {"artifact": self.descriptor},
            "error_code": None,
            "retryable": False,
        }

    def cancel(self, job_id):
        return {"id": job_id, "status": "cancel_requested", "model": "fastsam3d-plus-plus"}

    def artifact(self, job_id):
        return self.descriptor, self.path


def pair(runtime):
    request = {
        "clientIdentity": "agentscape",
        "contractVersion": "1",
        "origin": ORIGIN,
        "scopes": SCOPES,
    }
    first = runtime.sessions.pair(request, request_origin=ORIGIN)
    runtime.sessions.approve(first["pairingId"])
    paired = runtime.sessions.pair(
        {**request, "pairingId": first["pairingId"]}, request_origin=ORIGIN
    )
    token = str(paired["token"])
    session = runtime.sessions.authorize(f"Bearer {token}", "jobs.submit", request_origin=ORIGIN)
    return token, session


def three_d_request(snapshot, source, parent_id):
    body = {
        "provider": "modal-3d",
        "operation": "modal-3d.asset.image_to_3d.v1",
        "inputs": {
            "sourceArtifact": {
                "id": source["id"],
                "role": source["role"],
                "mime": source["mime"],
                "hash": source["hash"],
            },
            "model": "fastsam3d-plus-plus",
            "seed": 9,
        },
        "profile": "recommended",
        "options": {},
        "outputRoles": ["primary-glb"],
        "parent": {"jobId": parent_id},
        "retention": None,
        "metadata": None,
        "operationVersion": "1",
        "contractVersion": "1",
        "capabilityHash": snapshot["hash"],
        "capabilityRevision": snapshot["revision"],
    }
    body["requestHash"] = request_hash(body)
    body["idempotencyKey"] = idempotency_key(body)
    return body


def test_connector_composes_builtin_2d_artifact_into_builtin_3d(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODAL_GEN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        "modal_2d_client.provider.capabilities.document",
        lambda *, refresh_remote=False: {"models": [{"id": "sana-sprint-1.6b"}]},
    )
    jobs_2d = Fake2DJobs(tmp_path)
    jobs_3d = Fake3DJobs(tmp_path)
    adapters = adapt_providers([Modal2DProvider(jobs_2d), Modal3DProvider(jobs_3d)])
    runtime = build_runtime(Store(tmp_path / "connector.sqlite3"), adapters=adapters)
    _token, session = pair(runtime)
    snapshot = runtime.capabilities.get(str(session["capability_hash"]))
    assert snapshot is not None
    assert [provider["id"] for provider in snapshot["providers"]] == ["modal-2d", "modal-3d"]

    image_job = runtime.jobs.submit(make_request(snapshot), session)
    image_job = runtime.jobs.get(str(image_job["id"]), session)
    source = image_job["result"]["artifacts"][0]
    assert source["role"] == "primary-image"

    model_job = runtime.jobs.submit(
        three_d_request(snapshot, source, str(image_job["id"])),
        session,
    )
    assert jobs_3d.source == PNG
    finished = runtime.jobs.get(str(model_job["id"]), session)
    assert finished["status"] == "succeeded"
    assert finished["relations"] == [{"type": "parent", "jobId": image_job["id"]}]
    artifact = finished["result"]["artifacts"][0]
    assert artifact["role"] == "primary-glb"
    assert artifact["id"].startswith("artifact_")
    assert artifact["id"] != "provider_glb_01"

    _row, path = runtime.artifacts.open(
        str(artifact["id"]), owner_client="agentscape", owner_origin=ORIGIN
    )
    assert path.read_bytes() == GLB
