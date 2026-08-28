from __future__ import annotations

import asyncio
import threading

import httpx
from fastapi.testclient import TestClient

from modal_3d_client.app import create_app


class Store:
    def list(self, limit=50):
        return []


class Service:
    store = Store()

    def submit(self, data, **kwargs):
        return {"id": kwargs["job_id"], "status": "running", "model": kwargs["model"]}

    def poll(self, job_id):
        return {"id": job_id, "status": "running"}

    def cancel(self, job_id):
        return {"id": job_id, "status": "cancel_requested"}


def test_job_api_accepts_source_image_upload(source_jpeg):
    client = TestClient(create_app(Service()))
    response = client.post(
        "/v1/jobs",
        files={"file": ("source.jpg", source_jpeg, "image/jpeg")},
        data={
            "model": "fastsam3d-plus-plus",
            "profile": "recommended",
            "seed": "42",
            "job_id": "req_1",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": "req_1",
        "status": "running",
        "model": "fastsam3d-plus-plus",
    }


def test_submit_offloads_blocking_work_so_cancel_route_stays_responsive(source_jpeg):
    entered = threading.Event()
    release = threading.Event()

    class BlockingService(Service):
        def submit(self, data, **kwargs):
            entered.set()
            release.wait(timeout=2)
            return {
                "id": kwargs["job_id"],
                "status": "cancel_requested",
                "model": kwargs["model"],
            }

    app = create_app(BlockingService())

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            post = asyncio.create_task(
                client.post(
                    "/v1/jobs",
                    files={"file": ("source.jpg", source_jpeg, "image/jpeg")},
                    data={
                        "model": "fastsam3d-plus-plus",
                        "profile": "recommended",
                        "seed": "42",
                        "job_id": "req_blocking",
                    },
                )
            )
            assert await asyncio.to_thread(entered.wait, 1)
            cancelled = await asyncio.wait_for(
                client.delete("/v1/jobs/req_blocking"), timeout=0.5
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancel_requested"
            release.set()
            response = await asyncio.wait_for(post, timeout=2)
            assert response.status_code == 200

    asyncio.run(scenario())
