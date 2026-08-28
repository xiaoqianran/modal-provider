from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from modal_gen.app import build_runtime, create_app
from modal_gen.storage import Store
from tests.test_connector_e2e import ORIGIN, PNG, SCOPES, Fake2DAdapter, make_request


class TamperedStreamAdapter(Fake2DAdapter):
    def iter_artifact(self, provider_job_id, artifact, *, state=None):
        assert provider_job_id == "provider_job_01"
        assert artifact == self.artifact
        yield PNG
        yield b"tampered"


def run(coro):
    return asyncio.run(coro)


def test_tampered_artifact_stream_fails_closed_without_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODAL_GEN_DATA_DIR", str(tmp_path / "data"))
    adapter = TamperedStreamAdapter()
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[adapter])
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
    token = str(paired["token"])
    session = runtime.sessions.authorize(f"Bearer {token}", "jobs.submit", request_origin=ORIGIN)
    snapshot = runtime.capabilities.get(str(session["capability_hash"]))
    assert snapshot is not None
    job = runtime.jobs.submit(make_request(snapshot), session)
    job = runtime.jobs.get(str(job["id"]), session)
    job = runtime.jobs.get(str(job["id"]), session)
    artifact_id = str(job["result"]["artifacts"][0]["id"])
    app = create_app(runtime)

    async def scenario():
        headers = {"Authorization": f"Bearer {token}", "Origin": ORIGIN, "Accept": "image/png"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            response = await client.get(f"/connector/v1/artifacts/{artifact_id}", headers=headers)
            assert response.status_code == 502
            assert response.json()["code"] == "ARTIFACT_INTEGRITY_FAILED"

    run(scenario())
    cache_root = tmp_path / "data" / "artifacts"
    if cache_root.exists():
        assert not [path for path in cache_root.rglob("*") if path.is_file()]
        assert not list(cache_root.rglob("*.part"))
