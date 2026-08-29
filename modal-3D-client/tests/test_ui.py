from __future__ import annotations

from fastapi.testclient import TestClient

from modal_3d_client.app import create_app, mount_ui
from modal_3d_client.demo import DemoJobService


def test_ui_config_reports_demo_and_token_state():
    client = TestClient(create_app())
    res = client.get("/ui/config")
    assert res.status_code == 200
    body = res.json()
    assert body["demo"] is False
    assert body["require_token"] is False
    assert "mediaTypes" in body["source"]


def test_static_ui_is_mounted_and_serves_index(monkeypatch, tmp_path):
    app = create_app()
    mount_ui(app)
    client = TestClient(app)
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/ui/index.html"
    res = client.get("/ui/")
    assert res.status_code == 200
    assert "modal-3D Client" in res.text
    assert '<model-viewer id="glb-viewer"' in res.text
    assert "model-viewer/4.3.1/model-viewer.min.js" in res.text
    css = client.get("/ui/styles.css")
    assert css.status_code == 200
    js = client.get("/ui/app.js")
    assert js.status_code == 200


def test_session_middleware_exempts_ui_paths(monkeypatch):
    monkeypatch.setenv("MODAL_3D_CLIENT_TOKEN", "secret-token")
    app = create_app()
    mount_ui(app)
    client = TestClient(app)

    # API requires the session header when a token is configured.
    assert client.get("/health").status_code == 401
    ok = client.get("/health", headers={"X-Modal-3D-Session": "secret-token"})
    assert ok.status_code == 200

    # UI assets and config are reachable so the page can boot and prompt.
    assert client.get("/ui/").status_code == 200
    assert client.get("/ui/config").status_code == 200
    assert client.get("/ui/styles.css").status_code == 200


def test_cors_allows_any_origin_by_default():
    client = TestClient(create_app())
    for origin in ("https://izmky1i1hd-3213.cnb.run", "https://anything-else.test", "http://localhost:5173"):
        res = client.get("/health", headers={"Origin": origin})
        assert res.status_code == 200
        assert res.headers["access-control-allow-origin"] == "*"


def test_cors_preflight_returns_empty_204():
    # A 204 must not carry a body; a JSON body here breaks Content-Length.
    client = TestClient(create_app())
    res = client.options(
        "/v1/jobs",
        headers={"Origin": "https://anything.test", "Access-Control-Request-Method": "POST"},
    )
    assert res.status_code == 204
    assert res.content == b""
    assert res.headers["access-control-allow-origin"] == "*"


def test_cors_narrows_to_configured_origin(monkeypatch):
    monkeypatch.setenv("MODAL_3D_CLIENT_ORIGIN", "https://trusted.test")
    client = TestClient(create_app())
    trusted = client.get("/health", headers={"Origin": "https://trusted.test"})
    assert trusted.headers["access-control-allow-origin"] == "https://trusted.test"
    other = client.get("/health", headers={"Origin": "https://other.test"})
    assert other.headers["access-control-allow-origin"] == "*"


def test_demo_service_resolves_jobs_in_memory():
    svc = DemoJobService()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    first = svc.submit(png, model="fastsam3d-plus-plus", profile="recommended", seed=42)
    assert first["status"] == "running"
    assert svc.store.list()  # appears in the store immediately

    state = svc.poll(first["id"])
    assert state["id"] == first["id"]

    cancelled = svc.cancel(first["id"])
    assert cancelled["status"] == "cancelled"


def test_demo_app_endpoints_round_trip(monkeypatch):
    monkeypatch.setenv("MODAL_3D_CLIENT_DEMO", "1")
    app = create_app()
    mount_ui(app)
    client = TestClient(app)

    models = client.get("/v1/models")
    assert models.status_code == 200
    assert any(m["id"] == "fastsam3d-plus-plus" for m in models.json()["models"])

    caps = client.get("/v1/capabilities")
    assert caps.status_code == 200
    assert caps.json()["contract"] == "modal-3d.capabilities.v3"

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    res = client.post(
        "/v1/jobs",
        files={"file": ("t.png", png, "image/png")},
        data={"model": "fastsam3d-plus-plus", "profile": "recommended", "seed": "42"},
    )
    assert res.status_code == 200
    job = res.json()
    assert job["status"] in {"running", "succeeded"}
