from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from modal_3d_client.provider import Modal3DProvider

from modal_gen.app import build_runtime, create_app
from modal_gen.identity import idempotency_key, request_hash
from modal_gen.providers.loader import adapt_providers
from modal_gen.storage import Store
from tests.test_connector_2d3d_e2e import Fake3DJobs, StubModal3DProvider
from tests.test_connector_e2e import ORIGIN, PNG

SCOPES = [
    "capabilities.read",
    "jobs.submit",
    "jobs.read",
    "jobs.cancel",
    "artifacts.read",
    "artifacts.write",
]


def _pair(runtime, scopes=SCOPES):
    request = {
        "clientIdentity": "agentscape",
        "contractVersion": "1",
        "origin": ORIGIN,
        "scopes": list(scopes),
    }
    first = runtime.sessions.pair(request, request_origin=ORIGIN)
    runtime.sessions.approve(first["pairingId"])
    paired = runtime.sessions.pair(
        {**request, "pairingId": first["pairingId"]}, request_origin=ORIGIN
    )
    token = str(paired["token"])
    session = runtime.sessions.authorize(f"Bearer {token}", "jobs.submit", request_origin=ORIGIN)
    return token, session


def _three_d_request(snapshot, source):
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
        "parent": None,
        "retention": None,
        "metadata": {"purpose": "local-image-to-3d"},
        "operationVersion": "1",
        "contractVersion": "1",
        "capabilityHash": snapshot["hash"],
        "capabilityRevision": snapshot["revision"],
    }
    body["requestHash"] = request_hash(body)
    body["idempotencyKey"] = idempotency_key(body)
    return body


def test_uploaded_png_becomes_direct_modal3d_input_without_parent_job(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODAL_GEN_DATA_DIR", str(tmp_path / "data"))
    jobs_3d = Fake3DJobs(tmp_path)
    adapters = adapt_providers([StubModal3DProvider(jobs_3d)])
    runtime = build_runtime(Store(tmp_path / "connector.sqlite3"), adapters=adapters)
    token, session = _pair(runtime)
    snapshot = runtime.capabilities.get(str(session["capability_hash"]))
    assert snapshot is not None
    app = create_app(runtime)

    async def scenario():
        headers = {"Authorization": f"Bearer {token}", "Origin": ORIGIN}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            first = await client.post(
                "/connector/v1/artifacts",
                headers={**headers, "Content-Type": "image/png"},
                content=PNG,
            )
            assert first.status_code == 201
            source = first.json()["artifact"]
            assert source["role"] == "primary-image"
            assert source["mime"] == "image/png"
            assert source["bytes"] == len(PNG)

            duplicate = await client.post(
                "/connector/v1/artifacts",
                headers={**headers, "Content-Type": "image/png"},
                content=PNG,
            )
            assert duplicate.status_code == 201
            assert duplicate.json()["artifact"]["id"] == source["id"]

            listed = await client.get("/connector/v1/artifacts?mime=image%2Fpng", headers=headers)
            assert listed.status_code == 200
            uploaded = next(
                item for item in listed.json()["artifacts"] if item["id"] == source["id"]
            )
            assert uploaded["source"] == "uploaded"
            assert uploaded["jobId"] is None

            downloaded = await client.get(
                f"/connector/v1/artifacts/{source['id']}",
                headers={**headers, "Accept": "image/png"},
            )
            assert downloaded.status_code == 200
            assert downloaded.content == PNG

            submitted = await client.post(
                "/connector/v1/jobs",
                headers={**headers, "Content-Type": "application/json"},
                json=_three_d_request(snapshot, source),
            )
            assert submitted.status_code == 200
            job = submitted.json()["job"]
            assert job["relations"] == []

            finished = await client.get(f"/connector/v1/jobs/{job['id']}", headers=headers)
            assert finished.status_code == 200
            assert finished.json()["job"]["status"] == "succeeded"

    asyncio.run(scenario())
    assert jobs_3d.source == PNG


def test_artifact_upload_requires_write_scope_and_png(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODAL_GEN_DATA_DIR", str(tmp_path / "data"))
    runtime = build_runtime(
        Store(tmp_path / "connector.sqlite3"),
        adapters=adapt_providers([Modal3DProvider(Fake3DJobs(tmp_path))]),
    )
    token, _session = _pair(
        runtime, scopes=[scope for scope in SCOPES if scope != "artifacts.write"]
    )
    app = create_app(runtime)

    async def scenario():
        base = {"Authorization": f"Bearer {token}", "Origin": ORIGIN}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            denied = await client.post(
                "/connector/v1/artifacts",
                headers={**base, "Content-Type": "image/png"},
                content=PNG,
            )
            assert denied.status_code == 403

    asyncio.run(scenario())

    runtime2 = build_runtime(
        Store(tmp_path / "connector-2.sqlite3"),
        adapters=adapt_providers([Modal3DProvider(Fake3DJobs(tmp_path))]),
    )
    token2, _session2 = _pair(runtime2)
    app2 = create_app(runtime2)

    async def wrong_mime():
        headers = {"Authorization": f"Bearer {token2}", "Origin": ORIGIN}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app2), base_url="http://127.0.0.1:48123"
        ) as client:
            response = await client.post(
                "/connector/v1/artifacts",
                headers={**headers, "Content-Type": "image/jpeg"},
                content=PNG,
            )
            assert response.status_code == 415

    asyncio.run(wrong_mime())
