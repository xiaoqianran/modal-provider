from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient

from modal_gen.app import build_runtime
from modal_gen.errors import ConnectorError
from modal_gen.providers.loader import adapt_providers
from modal_gen.storage import Store
from modal_gen.studio.app import create_app
from modal_gen.studio.auth import StudioAuth
from modal_gen.studio.service import IMAGE_3D, TEXT_IMAGE, StudioService
from tests.test_connector_2d3d_e2e import (
    GLB,
    Fake2DJobs,
    Fake3DJobs,
    StubModal2DProvider,
    StubModal3DProvider,
)
from tests.test_connector_e2e import PNG


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("MODAL_GEN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STUDIO_AUTH_MODE", "development")
    monkeypatch.setenv("STUDIO_DEV_TOKEN", "test-token-with-at-least-24-characters")
    monkeypatch.setenv("STUDIO_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.setattr(
        "modal_2d_client.provider.capabilities.document",
        lambda **_: {"models": [{"id": "sana-sprint-1.6b"}]},
    )
    jobs = Fake3DJobs(tmp_path)
    adapters = adapt_providers(
        [
            StubModal2DProvider(Fake2DJobs(tmp_path)),
            StubModal3DProvider(jobs),
        ]
    )
    runtime = build_runtime(Store(tmp_path / "connector.sqlite3"), adapters=adapters)
    return StudioService(runtime, tmp_path / "studio.sqlite3")


def image_spec():
    return {"operation": TEXT_IMAGE, "inputs": {"prompt": "a castle", "model": "sana-sprint-1.6b"}}


def finish(studio, job, owner="alice"):
    for _ in range(6):
        studio.tick()
    return studio.owned("job", owner, job["id"])


def test_image_to_model_workflow_survives_restart(studio):
    job = studio.submit(
        "alice",
        {
            "operation": "studio.text_to_3d.v1",
            "inputs": {
                "prompt": "castle",
                "imageModel": "sana-sprint-1.6b",
                "model": "fastsam3d-plus-plus",
                "seed": 9,
            },
        },
        "workflow-key-1",
    )
    studio.tick()  # Submitted image; simulate application restart before completion.
    restarted = StudioService(studio.hub, studio.store.path)
    done = finish(restarted, job)
    assert done["status"] == "succeeded", done
    assert len(done["steps"]) == 2
    artifacts = done["result"]["artifacts"]
    assert artifacts[0]["mime"] == "model/gltf-binary"
    asset = restarted.owned("asset", "alice", artifacts[0]["id"])
    assert len(asset["parents"]) == 1
    assert restarted.open_asset("alice", asset["id"])[1].read_bytes() == GLB


def test_upload_and_owner_isolation(studio):
    source = studio.upload("alice", PNG, "image/png", "source.png")
    spec = {
        "operation": IMAGE_3D,
        "inputs": {
            "sourceArtifact": {"id": source["id"]},
            "model": "fastsam3d-plus-plus",
            "seed": 9,
        },
    }
    with pytest.raises(ConnectorError, match="not found"):
        studio.submit("bob", spec, "cross-user-key")
    job = studio.submit("alice", spec, "image-3d-key")
    assert finish(studio, job)["status"] == "succeeded"
    with pytest.raises(ConnectorError, match="not found"):
        studio.open_asset("bob", source["id"])


def test_idempotency_conflict_and_distinct_intents(studio):
    one = studio.submit("alice", image_spec(), "same-key-123")
    two = studio.submit("alice", image_spec(), "same-key-123")
    assert one["id"] == two["id"]
    with pytest.raises(ConnectorError, match="different request"):
        studio.submit("alice", {**image_spec(), "inputs": {"prompt": "changed"}}, "same-key-123")
    three = studio.submit("alice", image_spec(), "new-key-123")
    assert three["id"] != one["id"]
    assert finish(studio, one)["status"] == "succeeded"
    assert finish(studio, three)["status"] == "succeeded"
    assert (
        studio.owned("job", "alice", one["id"])["steps"][0]["id"]
        != studio.owned("job", "alice", three["id"])["steps"][0]["id"]
    )


def test_queued_cancel_never_dispatches(studio):
    job = studio.submit("alice", image_spec(), "cancel-key-123")
    studio.cancel("alice", job["id"])
    done = finish(studio, job)
    assert done["status"] == "cancelled" and done["steps"] == []


def test_uncertain_submission_is_not_replayed(studio, monkeypatch):
    calls = []

    def interrupted(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("connection dropped after dispatch")

    monkeypatch.setattr(studio.hub.jobs, "submit", interrupted)
    job = studio.submit("alice", image_spec(), "uncertain-key")
    done = finish(studio, job)
    assert done["status"] == "submission_unknown"
    assert len(calls) == 1


def test_glb_upload_and_invalid_header(studio):
    asset = studio.upload("alice", GLB, "model/gltf-binary", "model.glb")
    assert asset["role"] == "primary-glb"
    with pytest.raises(ConnectorError):
        studio.upload("alice", b"not a glb", "model/gltf-binary", "bad.glb")


def test_api_auth_csrf_and_no_admin_routes(studio):
    with TestClient(create_app(studio, background=False)) as client:
        assert client.get("/api/v1/jobs").status_code == 401
        client.headers["authorization"] = "Bearer test-token-with-at-least-24-characters"
        assert client.get("/v1/providers").status_code == 404
        assert client.get("/api/v1/jobs").json() == {"jobs": []}
        assert (
            client.post(
                "/api/v1/projects",
                json={"name": "project"},
                headers={"origin": "https://evil.example"},
            ).status_code
            == 403
        )
        upload = client.post(
            "/api/v1/uploads?name=source.png", content=PNG, headers={"content-type": "image/png"}
        )
        assert upload.status_code == 201
        asset = upload.json()["asset"]
        assert client.get(f"/api/v1/assets/{asset['id']}/content").content == PNG
        response = client.post(
            "/api/v1/jobs", json=image_spec(), headers={"Idempotency-Key": "api-key-123"}
        )
        assert response.status_code == 202, response.text


def test_access_requires_valid_signature_audience_and_gateway(monkeypatch):
    import time

    from cryptography.hazmat.primitives.asymmetric import rsa
    from starlette.requests import Request

    monkeypatch.setenv("STUDIO_AUTH_MODE", "access")
    monkeypatch.setenv("STUDIO_ACCESS_ISSUER", "https://team.cloudflareaccess.com")
    monkeypatch.setenv("STUDIO_ACCESS_AUD", "studio-audience")
    monkeypatch.setenv("STUDIO_EDGE_SECRET", "s" * 32)
    monkeypatch.setenv("STUDIO_ALLOWED_ORIGINS", "https://studio.example.com")
    auth = StudioAuth()
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        auth.keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=private.public_key())
    )
    claims = {
        "sub": "alice",
        "email": "alice@example.com",
        "iss": auth.issuer,
        "aud": auth.audience,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }

    def request(token, secret="s" * 32):
        return Request(
            {
                "type": "http",
                "method": "GET",
                "headers": [
                    (b"cf-access-jwt-assertion", token.encode()),
                    (b"x-studio-edge-secret", secret.encode()),
                ],
            }
        )

    token = jwt.encode(claims, private, algorithm="RS256")
    assert auth.owner(request(token)).startswith("user_")
    for bad in [
        request(token, "wrong"),
        request(jwt.encode({**claims, "aud": "other"}, private, algorithm="RS256")),
    ]:
        with pytest.raises(ConnectorError):
            auth.owner(bad)


def test_archive_failure_does_not_mark_task_complete(studio):
    class Archive:
        def put(self, *args):
            raise RuntimeError("storage unavailable")

    studio.archive = Archive()
    job = studio.submit("alice", image_spec(), "archive-key")
    done = finish(studio, job)
    assert done["status"] != "succeeded"
    assert studio.store.list("asset", "alice") == []
    studio.archive = None
    assert finish(studio, job)["status"] == "succeeded"
