from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from modal_gen.app import build_runtime, create_app
from modal_gen.storage import Store
from tests.test_connector_e2e import ORIGIN, SCOPES, Fake2DAdapter


def run(coro):
    return asyncio.run(coro)


def test_session_and_capability_survive_connector_restart(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODAL_GEN_AGENT_TOKEN", "local-secret")
    db_path = tmp_path / "connector.sqlite3"
    first_runtime = build_runtime(Store(db_path), adapters=[Fake2DAdapter()])
    first_app = create_app(first_runtime)
    token_holder = {}

    async def first_process():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=first_app), base_url="http://127.0.0.1:48123"
        ) as client:
            request = {
                "clientIdentity": "agentscape",
                "contractVersion": "1",
                "origin": ORIGIN,
                "scopes": SCOPES,
            }
            first = await client.post(
                "/connector/v1/session", json=request, headers={"Origin": ORIGIN}
            )
            pairing_id = first.json()["pairingId"]
            assert (
                await client.post(
                    f"/v1/pairings/{pairing_id}/approve",
                    headers={"X-Modal-Gen-Session": "local-secret"},
                )
            ).status_code == 200
            paired = await client.post(
                "/connector/v1/session",
                json={**request, "pairingId": pairing_id},
                headers={"Origin": ORIGIN},
            )
            token_holder["token"] = paired.json()["token"]
            token_holder["hash"] = paired.json()["session"]["capabilityHash"]

    run(first_process())
    token = token_holder["token"]
    assert token.encode() not in db_path.read_bytes()

    second_runtime = build_runtime(Store(db_path), adapters=[Fake2DAdapter()])
    second_app = create_app(second_runtime)

    async def second_process():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=second_app), base_url="http://127.0.0.1:48123"
        ) as client:
            response = await client.get(
                "/connector/v1/capabilities",
                headers={"Authorization": f"Bearer {token}", "Origin": ORIGIN},
            )
            assert response.status_code == 200
            assert response.json()["hash"] == token_holder["hash"]

    run(second_process())
