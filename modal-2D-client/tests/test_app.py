import asyncio

import httpx

from modal_2d_client import capabilities, modal_session
from modal_2d_client.app import create_app


class Store:
    def list(self, limit=50):
        return []


class Service:
    store = Store()

    def submit(self, payload, *, job_id=None):
        return {"id": job_id or "job_01", "status": "running", "model": payload["model"]}

    def poll(self, job_id):
        if job_id == "missing":
            raise KeyError(job_id)
        return {"id": job_id, "status": "running"}

    def cancel(self, job_id):
        return {"id": job_id, "status": "cancel_requested"}

    def artifact(self, job_id, index=None):
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


def test_api_accepts_safe_connector_job_id_and_rejects_unsafe_id():
    async def scenario():
        async with await client_for(create_app(Service())) as client:
            response = await client.post(
                "/v1/jobs",
                json={"prompt": "x", "job_id": "job_connector_2d"},
            )
            assert response.status_code == 200
            assert response.json()["id"] == "job_connector_2d"

            invalid = await client.post(
                "/v1/jobs",
                json={"prompt": "x", "job_id": "../escape"},
            )
            assert invalid.status_code == 422

    run(scenario())


def test_api_rejects_steps_override():
    async def scenario():
        async with await client_for(create_app(Service())) as client:
            response = await client.post("/v1/jobs", json={"prompt": "x", "steps": 2})
            assert response.status_code == 422

    run(scenario())


def test_optional_agent_session_protects_loopback_api(monkeypatch):
    monkeypatch.setenv("MODAL_2D_AGENT_TOKEN", "session-secret")

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            unauthorized = await client.get("/health")
            assert unauthorized.status_code == 401
            assert "session-secret" not in unauthorized.text

            authorized = await client.get(
                "/health",
                headers={"X-Modal-2D-Session": "session-secret"},
            )
            assert authorized.status_code == 200

    run(scenario())


def test_openapi_docs_are_disabled():
    async def scenario():
        async with await client_for(create_app(Service())) as client:
            assert (await client.get("/docs")).status_code == 404
            assert (await client.get("/redoc")).status_code == 404

    run(scenario())


def test_artifact_route_exposes_immutable_identity_headers(tmp_path):
    data = b"\x89PNG\r\n\x1a\nbody"
    path = tmp_path / "image.png"
    path.write_bytes(data)

    class ArtifactService(Service):
        def artifact(self, job_id):
            return (
                {
                    "id": "art_abc",
                    "sha256": "a" * 64,
                },
                path,
            )

    async def scenario():
        async with await client_for(create_app(ArtifactService())) as client:
            response = await client.get("/v1/jobs/job_01/artifact")
            assert response.status_code == 200
            assert response.content == data
            assert response.headers["etag"] == f'"{"a" * 64}"'
            assert response.headers["x-artifact-id"] == "art_abc"
            assert response.headers["x-artifact-sha256"] == "a" * 64
            assert response.headers["content-type"].startswith("image/png")

    run(scenario())


def test_api_accepts_batch_seeds_as_one_job():
    class BatchService(Service):
        def __init__(self):
            self.payload = None
        def submit(self, payload, *, job_id=None):
            self.payload = payload
            return {"id": job_id or "job_batch", "status": "running", "model": payload["model"]}
    service = BatchService()
    async def scenario():
        async with await client_for(create_app(service)) as client:
            response = await client.post("/v1/jobs", json={
                "prompt": "red apple",
                "seeds": [42, 73, 104, 135],
                "job_id": "job_batch",
            })
            assert response.status_code == 200
            assert service.payload["seeds"] == [42, 73, 104, 135]
            invalid = await client.post("/v1/jobs", json={"prompt": "x", "seed": 42, "seeds": [73]})
            assert invalid.status_code == 422
    run(scenario())
