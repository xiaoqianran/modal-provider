from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from modal_gen.app import build_runtime
from modal_gen.identity import idempotency_key, request_hash
from modal_gen.providers.modal3d import Modal3DAdapter
from modal_gen.storage import Store
from tests.test_connector_e2e import ORIGIN, SCOPES, Fake2DAdapter, make_request

GLB = b"glTF" + (2).to_bytes(4, "little") + (16).to_bytes(4, "little") + b"data"


class Tracking2D(Fake2DAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.artifact_reads = 0

    def iter_artifact(self, provider_job_id, artifact, *, state=None):
        self.artifact_reads += 1
        yield from super().iter_artifact(provider_job_id, artifact, state=state)


class ThreeDHarness:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.upload_contains_png = False
        self.expected_request_id: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={
                    "hardware": {},
                    "preprocessing": {
                        "kind": "rembg",
                        "local_only": True,
                        "canonical_size": 1024,
                        "model_downloaded": True,
                        "download": {"status": "ready", "integrity": "verified"},
                    },
                },
            )
        if request.method == "GET" and request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "fastsam3d-plus-plus",
                        "name": "FastSAM3D++",
                        "description": "fast",
                        "status": "enabled",
                        "output": "geometry",
                        "warm_seconds": 6.06,
                        "profiles": [{"id": "recommended", "name": "推荐"}],
                    }
                ],
            )
        if request.method == "POST" and request.url.path == "/v1/projects":
            body = request.read()
            self.upload_contains_png = b"\x89PNG\r\n\x1a\n" in body
            assert b"provider_art_01" not in body
            return httpx.Response(200, json={"id": "project_3d", "status": "draft"})
        if request.method == "POST" and request.url.path == "/v1/projects/project_3d/preprocess":
            return httpx.Response(
                200,
                json={
                    "canonical": {
                        "id": "can_3d",
                        "role": "canonical-rgba",
                        "mime": "image/png",
                        "bytes": 1024,
                        "sha256": "b" * 64,
                        "width": 1024,
                        "height": 1024,
                        "mode": "RGBA",
                    }
                },
            )
        if request.method == "POST" and request.url.path == "/v1/projects/project_3d/generation":
            assert json.loads(request.content) == {
                "request_id": self.expected_request_id,
                "model": "fastsam3d-plus-plus",
                "profile": "recommended",
                "seed": 9,
            }
            return httpx.Response(
                200,
                json={
                    "project": {"id": "project_3d"},
                    "job": {
                        "id": "provider_job_3d",
                        "model": "fastsam3d-plus-plus",
                        "status": "running",
                    },
                },
            )
        if request.method == "GET" and request.url.path == "/v1/jobs/provider_job_3d":
            return httpx.Response(
                200,
                json={
                    "id": "provider_job_3d",
                    "model": "fastsam3d-plus-plus",
                    "status": "succeeded",
                    "result": {
                        "artifact": {
                            "id": "provider_glb_3d",
                            "role": "primary-glb",
                            "mime": "model/gltf-binary",
                            "bytes": len(GLB),
                            "sha256": hashlib.sha256(GLB).hexdigest(),
                        }
                    },
                    "retryable": False,
                },
            )
        if request.method == "GET" and request.url.path == "/v1/jobs/provider_job_3d/artifact":
            return httpx.Response(
                200,
                content=GLB,
                headers={"content-type": "model/gltf-binary"},
            )
        raise AssertionError(f"unexpected 3D request: {request.method} {request.url.path}")


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


def test_connector_composes_2d_artifact_into_3d_and_recovers_after_restart(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("MODAL_GEN_DATA_DIR", str(tmp_path / "data"))
    two_d = Tracking2D()
    harness = ThreeDHarness()
    three_d = Modal3DAdapter(
        endpoint="http://127.0.0.1:3213",
        client=httpx.Client(transport=httpx.MockTransport(harness)),
    )
    db_path = tmp_path / "connector.sqlite3"
    runtime = build_runtime(Store(db_path), adapters=[two_d, three_d])
    token, session = pair(runtime)
    snapshot = runtime.capabilities.get(str(session["capability_hash"]))
    assert snapshot is not None
    assert [provider["id"] for provider in snapshot["providers"]] == ["modal-2d", "modal-3d"]

    image_job = runtime.jobs.submit(make_request(snapshot), session)
    image_job = runtime.jobs.get(str(image_job["id"]), session)
    image_job = runtime.jobs.get(str(image_job["id"]), session)
    source = image_job["result"]["artifacts"][0]
    assert source["role"] == "primary-image"
    assert two_d.artifact_reads == 0

    model_request = three_d_request(snapshot, source, str(image_job["id"]))
    harness.expected_request_id = str(model_request["idempotencyKey"])
    model_job = runtime.jobs.submit(model_request, session)
    assert model_job["status"] == "accepted"
    assert two_d.artifact_reads == 1
    assert harness.upload_contains_png is True
    internal = runtime.store.get_job(str(model_job["id"]), "agentscape", ORIGIN)
    assert internal is not None
    assert internal["provider_state"] == {"projectId": "project_3d"}
    assert "project_3d" not in str(model_job)
    assert "provider_job_3d" not in str(model_job)

    restarted = build_runtime(Store(db_path), adapters=[two_d, three_d])
    restored_session = restarted.sessions.authorize(
        f"Bearer {token}", "jobs.read", request_origin=ORIGIN
    )
    finished = restarted.jobs.get(str(model_job["id"]), restored_session)
    assert finished["status"] == "succeeded"
    assert finished["relations"] == [{"type": "parent", "jobId": image_job["id"]}]
    result_artifact = finished["result"]["artifacts"][0]
    assert result_artifact["role"] == "primary-glb"
    assert result_artifact["id"].startswith("artifact_")
    assert result_artifact["id"] != "provider_glb_3d"

    artifact, path = restarted.artifacts.open(
        str(result_artifact["id"]),
        owner_client="agentscape",
        owner_origin=ORIGIN,
    )
    assert path.read_bytes() == GLB
    assert artifact["hash"] == f"sha256:{hashlib.sha256(GLB).hexdigest()}"
