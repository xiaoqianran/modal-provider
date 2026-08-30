from __future__ import annotations

import asyncio

import httpx

from modal_gen.app import build_runtime, create_app
from modal_gen.storage import Store


class Adapter:
    id = "modal-2d"


def test_deployment_api_returns_job_without_waiting_for_deploy(tmp_path, monkeypatch):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Adapter()])
    started = []
    job = {"id": "dep_test", "status": "queued"}
    monkeypatch.setattr(
        runtime.deployments,
        "start_deploy",
        lambda provider, **kwargs: started.append((provider, kwargs)) or job,
    )
    monkeypatch.setattr(
        runtime.deployments,
        "deployment_job",
        lambda job_id: {"id": job_id, "status": "running"},
    )
    monkeypatch.setattr(
        runtime.deployments,
        "deployment_jobs",
        lambda limit=20: {"jobs": [{"id": "dep_test", "status": "running"}], "limit": limit},
    )
    app = create_app(runtime)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            headers = {"X-Modal-Gen-Session": "wangran"}
            created = await client.post(
                "/v1/deployments/deploy",
                headers=headers,
                json={"provider": "modal-2d", "missingOnly": True},
            )
            assert created.status_code == 200
            assert created.json() == {"job": job}
            assert started == [
                (
                    "modal-2d",
                    {
                        "app_name": None,
                        "strategy": "rolling",
                        "environment_name": None,
                        "missing_only": True,
                        "force": False,
                    },
                )
            ]

            one = await client.get("/v1/deployments/jobs/dep_test", headers=headers)
            assert one.json()["job"]["status"] == "running"
            many = await client.get("/v1/deployments/jobs?limit=7", headers=headers)
            assert many.json()["limit"] == 7

    asyncio.run(scenario())


def test_deployment_status_is_200_when_modal_is_disconnected(tmp_path):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Adapter()])
    app = create_app(runtime)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            response = await client.get(
                "/v1/deployments", headers={"X-Modal-Gen-Session": "wangran"}
            )
            assert response.status_code == 200
            assert response.json()["connected"] is False

    asyncio.run(scenario())


def test_huggingface_secret_api_requires_modal_connection(tmp_path, monkeypatch):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Adapter()])
    app = create_app(runtime)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            headers = {"X-Modal-Gen-Session": "wangran"}
            status = await client.get("/v1/secrets/huggingface", headers=headers)
            assert status.status_code == 200
            assert status.json() == {"connected": False, "configured": False, "secrets": []}

            saved = await client.post(
                "/v1/secrets/huggingface", headers=headers, json={"token": "hf_demo"}
            )
            assert saved.status_code == 409
            assert saved.json()["code"] == "DEPLOYMENT_CREDENTIALS_REQUIRED"

    asyncio.run(scenario())


def test_deployment_api_force_redeploy_defaults_to_rollover(tmp_path, monkeypatch):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Adapter()])
    started = []
    monkeypatch.setattr(
        runtime.deployments,
        "start_deploy",
        lambda provider, **kwargs: (
            started.append((provider, kwargs)) or {"id": "dep_force", "status": "queued"}
        ),
    )
    app = create_app(runtime)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            response = await client.post(
                "/v1/deployments/deploy",
                headers={"X-Modal-Gen-Session": "wangran"},
                json={"provider": "modal-3d", "app": "modal-3d-fastsam3d", "force": True},
            )
            assert response.status_code == 200
            assert started == [
                (
                    "modal-3d",
                    {
                        "app_name": "modal-3d-fastsam3d",
                        "strategy": "rolling",
                        "environment_name": None,
                        "missing_only": False,
                        "force": True,
                    },
                )
            ]

    asyncio.run(scenario())


def test_deployment_api_rejects_invalid_force(tmp_path):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Adapter()])
    app = create_app(runtime)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            response = await client.post(
                "/v1/deployments/deploy",
                headers={"X-Modal-Gen-Session": "wangran"},
                json={"provider": "modal-2d", "force": "yes"},
            )
            assert response.status_code == 422
            assert response.json()["code"] == "DEPLOYMENT_FORCE_INVALID"

    asyncio.run(scenario())


def test_runtime_refresh_query_forces_deployment_and_capability_status(tmp_path, monkeypatch):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Adapter()])
    deployment_calls = []
    capability_calls = []

    async def fake_status(provider=None, *, environment_name=None, force=False):
        deployment_calls.append((provider, force))
        return {"connected": True, "providers": []}

    async def fake_snapshot(*, now=None, force_runtime=False):
        capability_calls.append(force_runtime)
        return {"providers": [], "hash": "sha256:test"}

    monkeypatch.setattr(runtime.deployments, "status_async", fake_status)
    monkeypatch.setattr(runtime.capabilities, "snapshot_async", fake_snapshot)
    app = create_app(runtime)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            headers = {"X-Modal-Gen-Session": "wangran"}
            deployments = await client.get("/v1/deployments?refresh=1", headers=headers)
            capabilities = await client.get("/v1/capabilities?refresh=1", headers=headers)
            assert deployments.status_code == capabilities.status_code == 200

    asyncio.run(scenario())
    assert deployment_calls == [(None, True)]
    assert capability_calls == [True]


def test_deployment_api_forwards_explicit_force_redeploy(tmp_path, monkeypatch):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[Adapter()])
    started = []
    monkeypatch.setattr(
        runtime.deployments,
        "start_deploy",
        lambda provider, **kwargs: (
            started.append((provider, kwargs)) or {"id": "dep_force", "status": "queued"}
        ),
    )
    app = create_app(runtime)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            response = await client.post(
                "/v1/deployments/deploy",
                headers={"X-Modal-Gen-Session": "wangran"},
                json={
                    "provider": "modal-2d",
                    "app": "modal-2d-sana-sprint",
                    "force": True,
                    "strategy": "rolling",
                },
            )
            assert response.status_code == 200

    asyncio.run(scenario())
    assert started == [
        (
            "modal-2d",
            {
                "app_name": "modal-2d-sana-sprint",
                "strategy": "rolling",
                "environment_name": None,
                "missing_only": False,
                "force": True,
            },
        )
    ]
