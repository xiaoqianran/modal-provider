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
                    },
                )
            ]

            one = await client.get("/v1/deployments/jobs/dep_test", headers=headers)
            assert one.json()["job"]["status"] == "running"
            many = await client.get("/v1/deployments/jobs?limit=7", headers=headers)
            assert many.json()["limit"] == 7

    asyncio.run(scenario())
