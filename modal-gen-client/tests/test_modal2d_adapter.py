from __future__ import annotations

import hashlib
import json

import httpx

from modal_gen.providers.base import ProviderContext
from modal_gen.providers.modal2d import _ARTIFACT_TIMEOUT, _PROVIDER_TIMEOUT, Modal2DAdapter

PNG = b"\x89PNG\r\n\x1a\nbody"
DIGEST = hashlib.sha256(PNG).hexdigest()


class NullArtifacts:
    def resolve_input(self, artifact_id, *, owner_client, owner_origin):
        raise AssertionError("modal-2D adapter must not resolve Connector artifacts")


CONTEXT = ProviderContext(
    owner_client="agentscape",
    owner_origin="https://xiaoqianran.github.io",
    request_id="idem_0123456789abcdef0123456789abcdef01234567",
    artifacts=NullArtifacts(),
)


def capability():
    return {
        "contract": "modal-2d.generation.v1",
        "provider": "modal-2d",
        "operation": "modal-2d.image.text_to_image.v1",
        "artifact": {
            "role": "primary-image",
            "mime": "image/png",
            "format": "png",
            "lossless": True,
        },
        "models": [
            {
                "id": "sana-sprint-0.6b",
                "steps": 2,
                "profiles": [{"id": "recommended", "steps": 2, "guidance": 4.5}],
            },
            {
                "id": "sana-sprint-1.6b",
                "steps": 2,
                "profiles": [{"id": "recommended", "steps": 2, "guidance": 4.5}],
            },
        ],
    }


def test_modal2d_adapter_matches_provider_agent_contract():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["X-Modal-2D-Session"] == "agent-secret"
        if request.method == "GET" and request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=capability())
        if request.method == "POST" and request.url.path == "/v1/jobs":
            body = json.loads(request.content)
            assert body == {
                "prompt": "mossy shrine",
                "model": "sana-sprint-0.6b",
                "seed": 42,
                "guidance": 4.5,
            }
            assert "steps" not in body
            return httpx.Response(
                200,
                json={"id": "provider_job_01", "model": body["model"], "status": "running"},
            )
        if request.method == "GET" and request.url.path == "/v1/jobs/provider_job_01":
            return httpx.Response(
                200,
                json={
                    "id": "provider_job_01",
                    "model": "sana-sprint-0.6b",
                    "status": "succeeded",
                    "result": {
                        "artifact": {
                            "id": "art_provider_01",
                            "role": "primary-image",
                            "mime": "image/png",
                            "format": "png",
                            "bytes": len(PNG),
                            "sha256": DIGEST,
                            "width": 1024,
                            "height": 1024,
                        }
                    },
                },
            )
        if request.method == "DELETE" and request.url.path == "/v1/jobs/provider_job_01":
            return httpx.Response(
                200,
                json={
                    "id": "provider_job_01",
                    "model": "sana-sprint-0.6b",
                    "status": "cancel_requested",
                },
            )
        if request.method == "GET" and request.url.path == "/v1/jobs/provider_job_01/artifact":
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = Modal2DAdapter(token="agent-secret", client=client)

    descriptor = adapter.descriptor()
    operation = descriptor["capabilities"][0]
    assert descriptor["id"] == "modal-2d"
    assert descriptor["health"] == "healthy"
    assert operation["output"]["roles"] == ["primary-image"]
    assert operation["input"]["limits"] == {"width": 1024, "height": 1024, "steps": 2}

    submitted = adapter.submit(
        operation="modal-2d.image.text_to_image.v1",
        inputs={
            "prompt": "mossy shrine",
            "model": "sana-sprint-0.6b",
            "seed": 42,
            "guidance": 4.5,
        },
        profile="recommended",
        options={},
        context=CONTEXT,
    )
    assert submitted.status == "running"

    finished = adapter.get(submitted.id)
    assert finished.status == "succeeded"
    assert finished.artifact is not None
    assert b"".join(adapter.iter_artifact(submitted.id, finished.artifact)) == PNG
    assert adapter.cancel(submitted.id).status == "cancel_requested"
    assert calls[0] == ("GET", "/v1/capabilities")


def test_modal2d_adapter_uses_short_control_and_long_artifact_timeouts():
    assert _PROVIDER_TIMEOUT.connect == 2.0
    assert _PROVIDER_TIMEOUT.read == 20.0
    assert _PROVIDER_TIMEOUT.write == 20.0
    assert _PROVIDER_TIMEOUT.pool == 2.0
    assert _ARTIFACT_TIMEOUT.connect == 2.0
    assert _ARTIFACT_TIMEOUT.read == 120.0
    assert _ARTIFACT_TIMEOUT.write == 20.0
    assert _ARTIFACT_TIMEOUT.pool == 2.0
