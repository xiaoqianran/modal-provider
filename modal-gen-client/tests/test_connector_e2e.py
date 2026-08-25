from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import httpx

from modal_gen.app import build_runtime, create_app
from modal_gen.identity import idempotency_key, request_hash
from modal_gen.providers.base import ProviderArtifact, ProviderJob
from modal_gen.storage import Store

ORIGIN = "https://xiaoqianran.github.io"
SCOPES = [
    "capabilities.read",
    "jobs.submit",
    "jobs.read",
    "jobs.cancel",
    "artifacts.read",
]
PNG = b"\x89PNG\r\n\x1a\nbody"


class Fake2DAdapter:
    id = "modal-2d"

    def __init__(self) -> None:
        self.polls = 0
        self.submit_count = 0
        self.submitted = None
        self.artifact = ProviderArtifact(
            id="provider_art_01",
            role="primary-image",
            mime="image/png",
            bytes=len(PNG),
            sha256=hashlib.sha256(PNG).hexdigest(),
        )

    def descriptor(self):
        return {
            "id": "modal-2d",
            "displayName": "Modal 2D",
            "version": "1",
            "health": "healthy",
            "status": "available",
            "contractVersion": "1",
            "artifactTransport": "connector-artifact",
            "capabilities": [
                {
                    "operation": "modal-2d.image.text_to_image.v1",
                    "version": "1",
                    "displayName": "Text to Image",
                    "category": "image-generation",
                    "status": "available",
                    "input": {"types": ["text"]},
                    "output": {
                        "roles": ["primary-image"],
                        "required": ["primary-image"],
                        "optional": [],
                    },
                    "profiles": {"recommended": {"steps": 2}},
                    "execution": {"async": True},
                    "prerequisites": {"authMode": "connector-session", "connection": True},
                    "support": {"cancel": True, "resume": True, "idempotency": True},
                    "artifactTransport": "connector-artifact",
                }
            ],
        }

    def unavailable_descriptor(self):
        value = self.descriptor()
        value["health"] = "unavailable"
        value["status"] = "disabled"
        value["capabilities"][0]["status"] = "disabled"
        return value

    def submit(self, *, operation, inputs, profile, options):
        self.submit_count += 1
        self.submitted = (operation, inputs, profile, options)
        return ProviderJob(id="provider_job_01", status="running", model=inputs.get("model"))

    def get(self, provider_job_id):
        assert provider_job_id == "provider_job_01"
        self.polls += 1
        if self.polls == 1:
            return ProviderJob(id=provider_job_id, status="running", model="sana-sprint-0.6b")
        return ProviderJob(
            id=provider_job_id,
            status="succeeded",
            model="sana-sprint-0.6b",
            artifact=self.artifact,
        )

    def cancel(self, provider_job_id):
        return ProviderJob(id=provider_job_id, status="cancel_requested")

    def iter_artifact(self, provider_job_id, artifact):
        assert provider_job_id == "provider_job_01"
        assert artifact == self.artifact
        yield PNG[:5]
        yield PNG[5:]


def run(coro):
    return asyncio.run(coro)


def make_request(capability):
    body = {
        "provider": "modal-2d",
        "operation": "modal-2d.image.text_to_image.v1",
        "inputs": {
            "prompt": "mossy shrine",
            "model": "sana-sprint-0.6b",
            "seed": 42,
            "guidance": 4.5,
        },
        "profile": "recommended",
        "options": {},
        "outputRoles": ["primary-image"],
        "parent": None,
        "retention": None,
        "metadata": None,
    }
    body["requestHash"] = request_hash(body)
    body["idempotencyKey"] = idempotency_key(body)
    body["operationVersion"] = "1"
    body["contractVersion"] = "1"
    body["capabilityHash"] = capability["hash"]
    body["capabilityRevision"] = capability["revision"]
    return body


def test_full_pair_capability_job_artifact_contract(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODAL_GEN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MODAL_GEN_AGENT_TOKEN", "local-secret")
    adapter = Fake2DAdapter()
    runtime = build_runtime(Store(tmp_path / "connector.sqlite3"), adapters=[adapter])
    app = create_app(runtime)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            pairing_request = {
                "clientIdentity": "agentscape",
                "contractVersion": "1",
                "origin": ORIGIN,
                "scopes": SCOPES,
            }
            first = await client.post(
                "/connector/v1/session",
                json=pairing_request,
                headers={"Origin": ORIGIN},
            )
            assert first.status_code == 200
            approval = first.json()
            assert approval["status"] == "approval_required"
            pairing_id = approval["pairingId"]

            approved = await client.post(
                f"/v1/pairings/{pairing_id}/approve",
                headers={"X-Modal-Gen-Session": "local-secret"},
            )
            assert approved.status_code == 200
            assert approved.json()["status"] == "approved"

            paired = await client.post(
                "/connector/v1/session",
                json={**pairing_request, "pairingId": pairing_id},
                headers={"Origin": ORIGIN},
            )
            assert paired.status_code == 200
            payload = paired.json()
            assert payload["status"] == "paired"
            token = payload["token"]
            assert token not in str(payload["session"])
            auth = {"Authorization": f"Bearer {token}", "Origin": ORIGIN}

            cross_origin = await client.get(
                "/connector/v1/capabilities",
                headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"},
            )
            assert cross_origin.status_code == 403

            capability_response = await client.get("/connector/v1/capabilities", headers=auth)
            assert capability_response.status_code == 200
            capability = capability_response.json()
            assert capability["hash"] == payload["session"]["capabilityHash"]
            assert capability["providers"][0]["id"] == "modal-2d"

            submitted = await client.post(
                "/connector/v1/jobs",
                json=make_request(capability),
                headers=auth,
            )
            assert submitted.status_code == 200, submitted.text
            job = submitted.json()["job"]
            assert job["status"] == "accepted"
            assert job["eventSequence"] == 1
            assert "provider_job_01" not in str(job)
            job_id = job["id"]

            reused = await client.post(
                "/connector/v1/jobs",
                json=make_request(capability),
                headers=auth,
            )
            assert reused.status_code == 200
            assert reused.json()["job"]["id"] == job_id
            assert adapter.submit_count == 1

            running = await client.get(f"/connector/v1/jobs/{job_id}", headers=auth)
            assert running.json()["job"]["status"] == "running"
            assert running.json()["job"]["eventSequence"] == 2

            finished = await client.get(f"/connector/v1/jobs/{job_id}", headers=auth)
            result = finished.json()["job"]
            assert result["status"] == "succeeded"
            assert result["eventSequence"] == 3
            summary = result["result"]["artifacts"][0]
            assert summary["id"].startswith("artifact_")
            assert summary["id"] != "provider_art_01"
            assert summary["hash"] == f"sha256:{hashlib.sha256(PNG).hexdigest()}"

            artifact = await client.get(
                f"/connector/v1/artifacts/{summary['id']}",
                headers={**auth, "Accept": "image/png"},
            )
            assert artifact.status_code == 200
            assert artifact.content == PNG
            assert artifact.headers["x-artifact-id"] == summary["id"]
            assert artifact.headers["x-artifact-sha256"] == summary["hash"]

            revoked = await client.delete("/connector/v1/session", headers=auth)
            assert revoked.json() == {"status": "revoked"}
            denied = await client.get("/connector/v1/capabilities", headers=auth)
            assert denied.status_code == 401

    run(scenario())
    assert adapter.submitted[1]["prompt"] == "mossy shrine"


def test_pairing_requires_local_approval_and_origin_match(tmp_path: Path):
    runtime = build_runtime(Store(tmp_path / "connector.sqlite3"), adapters=[Fake2DAdapter()])
    app = create_app(runtime)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:48123"
        ) as client:
            body = {
                "clientIdentity": "agentscape",
                "contractVersion": "1",
                "origin": ORIGIN,
                "scopes": SCOPES,
            }
            wrong = await client.post(
                "/connector/v1/session",
                json=body,
                headers={"Origin": "https://evil.example"},
            )
            assert wrong.status_code == 403

            first = await client.post(
                "/connector/v1/session", json=body, headers={"Origin": ORIGIN}
            )
            pairing_id = first.json()["pairingId"]
            still_pending = await client.post(
                "/connector/v1/session",
                json={**body, "pairingId": pairing_id},
                headers={"Origin": ORIGIN},
            )
            assert still_pending.json()["status"] == "approval_required"

    run(scenario())
