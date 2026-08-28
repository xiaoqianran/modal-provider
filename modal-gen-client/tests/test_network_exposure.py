from __future__ import annotations

from pathlib import Path

import pytest

from modal_gen.app import create_app
from modal_gen.constants import allow_any_origin

ORIGIN = "http://localhost:3000"


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Keep MODAL_GEN_ALLOW_ANY_ORIGIN from leaking into other tests."""
    monkeypatch.delenv("MODAL_GEN_ALLOW_ANY_ORIGIN", raising=False)
    yield


def _app(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MODAL_GEN_DATA_DIR", str(tmp_path))
    return create_app()


def _pair(client, monkeypatch, origin=ORIGIN):
    body = {
        "clientIdentity": "agentscape",
        "contractVersion": "1",
        "origin": origin,
        "scopes": [
            "capabilities.read",
            "jobs.submit",
            "jobs.read",
            "jobs.cancel",
            "artifacts.read",
        ],
    }
    monkeypatch.setenv("MODAL_GEN_AGENT_TOKEN", "local-secret")
    first = client.post("/connector/v1/session", json=body, headers={"Origin": origin})
    pairing_id = first.json()["pairingId"]
    client.post(
        f"/v1/pairings/{pairing_id}/approve",
        headers={"X-Modal-Gen-Session": "local-secret"},
    )
    second = client.post(
        "/connector/v1/session", json={**body, "pairingId": pairing_id}, headers={"Origin": origin}
    )
    return second.json()["token"]


# --------------------------------------------------------------- default: locked
def test_allow_any_origin_defaults_off(monkeypatch):
    monkeypatch.delenv("MODAL_GEN_ALLOW_ANY_ORIGIN", raising=False)
    assert allow_any_origin() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "*"])
def test_allow_any_origin_accepts_truthy_values(monkeypatch, value):
    monkeypatch.setenv("MODAL_GEN_ALLOW_ANY_ORIGIN", value)
    assert allow_any_origin() is True


def test_cors_reflects_paired_origin_by_default(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    with TestClient(_app(monkeypatch, tmp_path)) as client:
        resp = client.options("/connector/v1/jobs", headers={"Origin": "https://site.example"})
        assert resp.headers["Access-Control-Allow-Origin"] == "https://site.example"


def test_cross_origin_request_still_rejected_by_default(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    with TestClient(_app(monkeypatch, tmp_path)) as client:
        token = _pair(client, monkeypatch)
        resp = client.get(
            "/connector/v1/jobs",
            headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"},
        )
        assert resp.status_code == 403


# ------------------------------------------------------------- relaxed: wildcard
def test_cors_wildcard_when_enabled(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MODAL_GEN_ALLOW_ANY_ORIGIN", "1")
    with TestClient(_app(monkeypatch, tmp_path)) as client:
        resp = client.options("/connector/v1/jobs", headers={"Origin": "https://any.example"})
        assert resp.headers["Access-Control-Allow-Origin"] == "*"
        assert resp.headers["Vary"] == "Origin"


def test_cross_origin_request_allowed_when_enabled(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MODAL_GEN_ALLOW_ANY_ORIGIN", "1")
    with TestClient(_app(monkeypatch, tmp_path)) as client:
        token = _pair(client, monkeypatch)
        resp = client.get(
            "/connector/v1/jobs",
            headers={"Authorization": f"Bearer {token}", "Origin": "https://other.example"},
        )
        assert resp.status_code == 200


def test_session_scope_and_token_still_enforced_when_relaxed(monkeypatch, tmp_path):
    """Relaxing the Origin boundary must not weaken authentication."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MODAL_GEN_ALLOW_ANY_ORIGIN", "1")
    with TestClient(_app(monkeypatch, tmp_path)) as client:
        _pair(client, monkeypatch, origin=ORIGIN)
        # no token -> still 401
        assert client.get("/connector/v1/jobs").status_code == 401
        # bad token -> still 401
        assert (
            client.get("/connector/v1/jobs", headers={"Authorization": "Bearer nope"}).status_code
            == 401
        )


def test_local_control_plane_still_locked_when_relaxed(monkeypatch, tmp_path):
    """`MODAL_GEN_ALLOW_ANY_ORIGIN` must not open the local control plane."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MODAL_GEN_ALLOW_ANY_ORIGIN", "1")
    monkeypatch.delenv("MODAL_GEN_AGENT_TOKEN", raising=False)
    with TestClient(_app(monkeypatch, tmp_path)) as client:
        assert client.get("/v1/pairings").status_code == 503
        monkeypatch.setenv("MODAL_GEN_AGENT_TOKEN", "local-secret")
        assert client.get("/v1/pairings").status_code == 401
        assert (
            client.get("/v1/pairings", headers={"X-Modal-Gen-Session": "local-secret"}).status_code
            == 200
        )


def test_allow_any_origin_ignores_unrelated_values(monkeypatch):
    monkeypatch.setenv("MODAL_GEN_ALLOW_ANY_ORIGIN", "0")
    assert allow_any_origin() is False
    monkeypatch.setenv("MODAL_GEN_ALLOW_ANY_ORIGIN", "")
    assert allow_any_origin() is False


def test_env_var_is_read_at_call_time(monkeypatch):
    """Must not be cached at import, or runtime configuration breaks."""
    monkeypatch.delenv("MODAL_GEN_ALLOW_ANY_ORIGIN", raising=False)
    assert allow_any_origin() is False
    monkeypatch.setenv("MODAL_GEN_ALLOW_ANY_ORIGIN", "1")
    assert allow_any_origin() is True
    monkeypatch.delenv("MODAL_GEN_ALLOW_ANY_ORIGIN")
    assert allow_any_origin() is False
