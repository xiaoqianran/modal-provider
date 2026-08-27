from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from modal_gen.errors import ProviderError
from modal_gen.providers.base import ConnectorArtifactInput, ProviderContext
from modal_gen.providers.modal3d import Modal3DAdapter
from modal_gen.providers.modal3d_discovery import AgentConnection

PNG = b"\x89PNG\r\n\x1a\nsource"
GLB = b"glTF" + (2).to_bytes(4, "little") + (16).to_bytes(4, "little") + b"data"


class Resolver:
    def __init__(self, path: Path) -> None:
        self.value = ConnectorArtifactInput(
            id="artifact_image",
            role="primary-image",
            mime="image/png",
            bytes=len(PNG),
            hash=f"sha256:{hashlib.sha256(PNG).hexdigest()}",
            path=path,
        )
        self.calls = []

    def resolve_input(self, artifact_id, *, owner_client, owner_origin):
        self.calls.append((artifact_id, owner_client, owner_origin))
        return self.value


def context(path: Path) -> ProviderContext:
    return ProviderContext(
        owner_client="agentscape",
        owner_origin="https://xiaoqianran.github.io",
        request_id="idem_0123456789abcdef0123456789abcdef01234567",
        artifacts=Resolver(path),
    )


def models():
    return [
        {
            "id": "fastsam3d-plus-plus",
            "name": "FastSAM3D++",
            "description": "fast",
            "status": "enabled",
            "output": "geometry",
            "warm_seconds": 6.06,
            "profiles": [{"id": "recommended", "name": "推荐"}],
        },
        {
            "id": "pixal3d",
            "name": "Pixal3D",
            "description": "textured",
            "status": "enabled",
            "output": "textured",
            "warm_seconds": 108.92,
            "profiles": [{"id": "recommended", "name": "推荐"}],
        },
    ]


def source_ref():
    return {
        "id": "artifact_image",
        "role": "primary-image",
        "mime": "image/png",
        "hash": f"sha256:{hashlib.sha256(PNG).hexdigest()}",
    }


class SequenceDiscovery:
    def __init__(self, *connections: AgentConnection) -> None:
        self.connections = list(connections)
        self.calls = 0

    def discover(self):
        self.calls += 1
        if not self.connections:
            return None
        if len(self.connections) == 1:
            return self.connections[0]
        return self.connections.pop(0)


def test_modal3d_adapter_maps_connector_artifact_to_project_pipeline(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(PNG)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["X-Modal-3D-Session"] == "agent-secret"
        if request.method == "GET" and request.url.path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={
                    "hardware": {},
                    "preprocessing": {
                        "kind": "rembg",
                        "local_only": True,
                        "canonical_size": 1024,
                        "model_downloaded": True,
                        "download": {"status": "ready", "integrity": "verified"},
                    },
                },
            )
        if request.method == "GET" and request.url.path == "/v1/models":
            return httpx.Response(200, json=models())
        if request.method == "POST" and request.url.path == "/v1/projects":
            body = request.read()
            assert PNG in body
            assert "multipart/form-data" in request.headers["content-type"]
            return httpx.Response(200, json={"id": "project_01", "status": "draft"})
        if request.method == "POST" and request.url.path == "/v1/projects/project_01/preprocess":
            return httpx.Response(
                200,
                json={
                    "canonical": {
                        "id": "can_01",
                        "role": "canonical-rgba",
                        "mime": "image/png",
                        "bytes": 1234,
                        "sha256": "a" * 64,
                        "width": 1024,
                        "height": 1024,
                        "mode": "RGBA",
                    }
                },
            )
        if request.method == "POST" and request.url.path == "/v1/projects/project_01/generation":
            assert json.loads(request.content) == {
                "request_id": "idem_0123456789abcdef0123456789abcdef01234567",
                "model": "fastsam3d-plus-plus",
                "profile": "recommended",
                "seed": 7,
            }
            return httpx.Response(
                200,
                json={
                    "project": {"id": "project_01"},
                    "job": {
                        "id": "job3d_01",
                        "model": "fastsam3d-plus-plus",
                        "status": "running",
                    },
                },
            )
        if request.method == "GET" and request.url.path == "/v1/jobs/job3d_01":
            return httpx.Response(
                200,
                json={
                    "id": "job3d_01",
                    "model": "fastsam3d-plus-plus",
                    "status": "succeeded",
                    "result": {
                        "artifact": {
                            "id": "provider_glb_01",
                            "role": "primary-glb",
                            "mime": "model/gltf-binary",
                            "bytes": len(GLB),
                            "sha256": hashlib.sha256(GLB).hexdigest(),
                        }
                    },
                    "retryable": False,
                },
            )
        if request.method == "GET" and request.url.path == "/v1/jobs/job3d_01/artifact":
            return httpx.Response(
                200,
                content=GLB,
                headers={"content-type": "model/gltf-binary"},
            )
        if request.method == "DELETE" and request.url.path == "/v1/jobs/job3d_01":
            return httpx.Response(
                200,
                json={
                    "id": "job3d_01",
                    "model": "fastsam3d-plus-plus",
                    "status": "cancel_requested",
                    "retryable": True,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    adapter = Modal3DAdapter(
        endpoint="http://127.0.0.1:3213",
        token="agent-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    ctx = context(source)

    descriptor = adapter.descriptor()
    capability = descriptor["capabilities"][0]
    assert descriptor["id"] == "modal-3d"
    assert capability["output"]["roles"] == ["primary-glb"]
    assert capability["input"]["schema"]["properties"]["model"]["enum"] == [
        "fastsam3d-plus-plus",
        "pixal3d",
    ]

    submitted = adapter.submit(
        operation="modal-3d.asset.image_to_3d.v1",
        inputs={"sourceArtifact": source_ref(), "model": "fastsam3d-plus-plus", "seed": 7},
        profile="recommended",
        options={},
        context=ctx,
    )
    assert submitted.status == "running"
    assert submitted.state == {"projectId": "project_01"}
    assert ctx.artifacts.calls == [
        ("artifact_image", "agentscape", "https://xiaoqianran.github.io")
    ]

    finished = adapter.get(submitted.id, state=submitted.state)
    assert finished.status == "succeeded"
    assert finished.state == submitted.state
    assert finished.artifact is not None
    assert (
        b"".join(adapter.iter_artifact(submitted.id, finished.artifact, state=submitted.state))
        == GLB
    )
    assert adapter.cancel(submitted.id, state=submitted.state).status == "cancel_requested"
    assert calls[:5] == [
        ("GET", "/v1/capabilities"),
        ("GET", "/v1/models"),
        ("POST", "/v1/projects"),
        ("POST", "/v1/projects/project_01/preprocess"),
        ("POST", "/v1/projects/project_01/generation"),
    ]


def test_modal3d_adapter_requires_configured_loopback_endpoint():
    adapter = Modal3DAdapter(
        endpoint=None, client=httpx.Client(transport=httpx.MockTransport(lambda _: None))
    )
    with pytest.raises(ProviderError) as exc:
        adapter.descriptor()
    assert exc.value.code == "PROVIDER_CONNECTION_REQUIRED"

    with pytest.raises(ValueError, match="loopback"):
        Modal3DAdapter(endpoint="http://192.168.1.10:3213")


def test_modal3d_adapter_rejects_source_descriptor_mismatch_before_provider_call(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(PNG)
    called = []
    adapter = Modal3DAdapter(
        endpoint="http://127.0.0.1:3213",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: called.append(request) or httpx.Response(500)
            )
        ),
    )
    bad = source_ref()
    bad["hash"] = "sha256:" + "0" * 64

    with pytest.raises(ProviderError) as exc:
        adapter.submit(
            operation="modal-3d.asset.image_to_3d.v1",
            inputs={"sourceArtifact": bad, "model": "fastsam3d-plus-plus", "seed": 42},
            profile="recommended",
            options={},
            context=context(source),
        )
    assert exc.value.code == "PROVIDER_SOURCE_MISMATCH"
    assert called == []


def test_modal3d_adapter_requires_verified_preprocess_model():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={
                    "hardware": {},
                    "preprocessing": {
                        "kind": "rembg",
                        "local_only": True,
                        "canonical_size": 1024,
                        "model_downloaded": False,
                        "download": {"status": "idle", "integrity": "unverified"},
                    },
                },
            )
        raise AssertionError("models must not be queried before preprocess is ready")

    adapter = Modal3DAdapter(
        endpoint="http://127.0.0.1:3213",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderError) as exc:
        adapter.descriptor()
    assert exc.value.code == "PROVIDER_PREREQUISITE_REQUIRED"
    assert exc.value.status == 503


def test_modal3d_adapter_refreshes_discovery_after_restart():
    first = AgentConnection("http://127.0.0.1:41001", "a" * 64, 101, 201)
    second = AgentConnection("http://127.0.0.1:41002", "b" * 64, 102, 202)
    discovery = SequenceDiscovery(first, second)
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("X-Modal-3D-Session")))
        return httpx.Response(
            200, json={"id": "job1", "model": "fastsam3d-plus-plus", "status": "running"}
        )

    adapter = Modal3DAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler)), discovery=discovery
    )
    assert adapter.get("job1").status == "running"
    assert adapter.get("job1").status == "running"
    assert seen == [
        ("http://127.0.0.1:41001/v1/jobs/job1", "a" * 64),
        ("http://127.0.0.1:41002/v1/jobs/job1", "b" * 64),
    ]
    assert discovery.calls == 2
