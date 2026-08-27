from __future__ import annotations

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


def test_job_api_accepts_canonical_upload(canonical_png):
    client = TestClient(create_app(Service()))
    response = client.post(
        "/v1/jobs",
        files={"file": ("canonical.png", canonical_png, "image/png")},
        data={"model": "fastsam3d-plus-plus", "profile": "recommended", "seed": "42", "job_id": "req_1"},
    )
    assert response.status_code == 200
    assert response.json() == {"id": "req_1", "status": "running", "model": "fastsam3d-plus-plus"}
