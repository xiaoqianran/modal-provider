import asyncio

import httpx

from modal_2d_client import capabilities, modal_session
from modal_2d_client.app import create_app


class Store:
    def list(self, limit=50):
        return []


class Service:
    store = Store()

    def submit(self, payload):
        return {"id": "job_01", "status": "running", "model": payload["model"]}

    def poll(self, job_id):
        if job_id == "missing":
            raise KeyError(job_id)
        return {"id": job_id, "status": "running"}

    def cancel(self, job_id):
        return {"id": job_id, "status": "cancel_requested"}

    def artifact(self, job_id):
        raise RuntimeError("not ready")


def run(coro):
    return asyncio.run(coro)


async def client_for(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


def test_local_api_is_small_and_credentials_are_not_echoed(monkeypatch):
    connected = {"value": False}

    def connect(token_id, token_secret):
        assert token_id == "token-id"
        assert token_secret == "token-secret"
        connected["value"] = True

    monkeypatch.setattr(modal_session, "connect", connect)
    monkeypatch.setattr(modal_session, "disconnect", lambda: connected.update(value=False))
    monkeypatch.setattr(modal_session, "connected", lambda: connected["value"])

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            response = await client.post(
                "/modal/connect",
                json={"token_id": "token-id", "token_secret": "token-secret"},
            )
            assert response.status_code == 200
            assert response.json() == {"connected": True}
            assert "token" not in response.text.lower()

            response = await client.post("/v1/jobs", json={"prompt": "mossy house"})
            assert response.status_code == 200
            assert response.json() == {
                "id": "job_01",
                "status": "running",
                "model": "sana-sprint-1.6b",
            }
            assert (await client.get("/v1/jobs/missing")).status_code == 404
            assert (await client.get("/v1/jobs/job_01/artifact")).status_code == 409

    run(scenario())


def test_capabilities_and_models_routes(monkeypatch, capability_doc):
    monkeypatch.setattr(capabilities, "document", lambda: capability_doc)
    monkeypatch.setattr(capabilities, "public_models", lambda: [{"id": "sana-sprint-1.6b"}])

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            capability = (await client.get("/v1/capabilities")).json()
            models = (await client.get("/v1/models")).json()
            assert capability["operation"] == "modal-2d.image.text_to_image.v1"
            assert models == {"models": [{"id": "sana-sprint-1.6b"}]}

    run(scenario())
