from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from modal_gen.app import build_runtime, create_app
from modal_gen.errors import ConnectorError
from modal_gen.storage import Store
from tests.test_connector_e2e import ORIGIN, SCOPES, Fake2DAdapter, make_request


def run(coro):
    return asyncio.run(coro)


def test_local_product_api_requires_session_gate(tmp_path: Path, monkeypatch):
    app = create_app(build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Fake2DAdapter()]))

    async def locked():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            response = await client.get("/v1/providers")
            assert response.status_code == 503
            assert response.json()["code"] == "LOCAL_CONTROL_LOCKED"

    run(locked())
    monkeypatch.setenv("MODAL_GEN_AGENT_TOKEN", "local-secret")

    async def guarded():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            assert (await client.get("/v1/providers")).status_code == 401
            authorized = await client.get(
                "/v1/providers", headers={"X-Modal-Gen-Session": "local-secret"}
            )
            assert authorized.status_code == 200
            assert "local-secret" not in authorized.text

    run(guarded())


def test_connector_preflight_is_origin_specific_and_private_network_aware(tmp_path: Path):
    app = create_app(build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Fake2DAdapter()]))

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            response = await client.options(
                "/connector/v1/session",
                headers={
                    "Origin": ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                    "Access-Control-Request-Private-Network": "true",
                },
            )
            assert response.status_code == 204
            assert response.headers["access-control-allow-origin"] == ORIGIN
            assert response.headers["access-control-allow-private-network"] == "true"
            assert "authorization" in response.headers["access-control-allow-headers"].lower()

    run(scenario())


def test_job_rejects_secret_fields_and_identity_tampering(tmp_path: Path):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Fake2DAdapter()])
    pairing = {
        "clientIdentity": "agentscape",
        "contractVersion": "1",
        "origin": ORIGIN,
        "scopes": SCOPES,
    }
    first = runtime.sessions.pair(pairing, request_origin=ORIGIN)
    runtime.sessions.approve(first["pairingId"])
    paired = runtime.sessions.pair(
        {**pairing, "pairingId": first["pairingId"]}, request_origin=ORIGIN
    )
    session = runtime.sessions.authorize(
        f"Bearer {paired['token']}", "jobs.submit", request_origin=ORIGIN
    )
    snapshot = runtime.capabilities.get(str(session["capability_hash"]))
    assert snapshot is not None

    secret = make_request(snapshot)
    secret["metadata"] = {"apiKey": "must-not-cross"}
    with pytest.raises(ConnectorError) as exc:
        runtime.jobs.submit(secret, session)
    assert exc.value.code == "JOB_SECRET_FIELD"

    tampered = make_request(snapshot)
    tampered["requestHash"] = "sha256:" + "0" * 64
    with pytest.raises(ConnectorError) as exc:
        runtime.jobs.submit(tampered, session)
    assert exc.value.code == "JOB_REQUEST_HASH_MISMATCH"


def test_connector_preflight_rejects_invalid_origin(tmp_path: Path):
    app = create_app(build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Fake2DAdapter()]))

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            response = await client.options(
                "/connector/v1/session",
                headers={"Access-Control-Request-Method": "POST"},
            )
            assert response.status_code == 403
            assert response.json()["code"] == "CONNECTOR_ORIGIN_REQUIRED"
            assert "access-control-allow-origin" not in response.headers

    run(scenario())


class ManagedFakeAdapter(Fake2DAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.connected = False

    def connection_status(self):
        return {"id": self.id, "connected": self.connected, "managed": True}

    def connect(self, token_id, token_secret):
        assert token_id
        assert token_secret
        self.connected = True
        return self.connection_status()

    def disconnect(self):
        self.connected = False
        return self.connection_status()


def test_local_control_manages_provider_connections_without_echoing_credentials(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("MODAL_GEN_AGENT_TOKEN", "local-secret")
    adapter = ManagedFakeAdapter()
    app = create_app(build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[adapter]))

    async def scenario():
        headers = {"X-Modal-Gen-Session": "local-secret"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            before = await client.get("/v1/provider-connections", headers=headers)
            assert before.json()["providers"][0]["connected"] is False

            connected = await client.post(
                "/v1/providers/connect",
                headers=headers,
                json={"tokenId": "id-value", "tokenSecret": "secret-value"},
            )
            assert connected.status_code == 200
            assert connected.json()["providers"][0]["connected"] is True
            assert "id-value" not in connected.text
            assert "secret-value" not in connected.text

            disconnected = await client.post("/v1/providers/disconnect", headers=headers)
            assert disconnected.status_code == 200
            assert disconnected.json()["providers"][0]["connected"] is False

    run(scenario())
