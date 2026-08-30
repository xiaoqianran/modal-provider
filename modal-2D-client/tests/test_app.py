import asyncio

import httpx

from modal_2d_client import capabilities, modal_session
from modal_2d_client.app import create_app


class Store:
    def list(self, limit=50):
        return []


class Service:
    store = Store()

    def submit(self, payload, *, job_id=None):
        return {"id": job_id or "job_01", "status": "running", "model": payload["model"]}

    def poll(self, job_id):
        if job_id == "missing":
            raise KeyError(job_id)
        return {"id": job_id, "status": "running"}

    def cancel(self, job_id):
        return {"id": job_id, "status": "cancel_requested"}

    def artifact(self, job_id, index=None):
        raise RuntimeError("not ready")


def run(coro):
    return asyncio.run(coro)


async def client_for(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


def test_local_api_is_small_and_credentials_are_not_echoed(monkeypatch):
    connected = {"value": False}

    def connect(token_id, token_secret):
        assert token_id == "token-id"
        assert token_secret == "token-secret"
        connected["value"] = True

    monkeypatch.setattr(modal_session, "connect", connect)
    monkeypatch.setattr(modal_session, "disconnect", lambda: connected.update(value=False))
    monkeypatch.setattr(modal_session, "connected", lambda: connected["value"])
    monkeypatch.setattr(capabilities, "refresh", lambda: {"models": []})

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            response = await client.post(
                "/modal/connect",
                json={"token_id": "token-id", "token_secret": "token-secret"},
            )
            assert response.status_code == 200
            assert response.json() == {"connected": True}
            assert "token" not in response.text.lower()

            response = await client.post("/v1/jobs", json={"prompt": "mossy house"})
            assert response.status_code == 200
            assert response.json() == {
                "id": "job_01",
                "status": "running",
                "model": "sana-sprint-1.6b",
            }
            assert (await client.get("/v1/jobs/missing")).status_code == 404
            assert (await client.get("/v1/jobs/job_01/artifact")).status_code == 409

    run(scenario())


def test_capabilities_and_models_routes(monkeypatch, capability_doc):
    monkeypatch.setattr(capabilities, "document", lambda **_kwargs: capability_doc)
    monkeypatch.setattr(capabilities, "public_models", lambda: [{"id": "sana-sprint-1.6b"}])

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            capability = (await client.get("/v1/capabilities")).json()
            models = (await client.get("/v1/models")).json()
            assert capability["operation"] == "modal-2d.image.text_to_image.v1"
            assert models == {"models": [{"id": "sana-sprint-1.6b"}]}

    run(scenario())


def test_api_accepts_safe_connector_job_id_and_rejects_unsafe_id():
    async def scenario():
        async with await client_for(create_app(Service())) as client:
            response = await client.post(
                "/v1/jobs",
                json={"prompt": "x", "job_id": "job_connector_2d"},
            )
            assert response.status_code == 200
            assert response.json()["id"] == "job_connector_2d"

            invalid = await client.post(
                "/v1/jobs",
                json={"prompt": "x", "job_id": "../escape"},
            )
            assert invalid.status_code == 422

    run(scenario())


def test_api_rejects_steps_override():
    async def scenario():
        async with await client_for(create_app(Service())) as client:
            response = await client.post("/v1/jobs", json={"prompt": "x", "steps": 2})
            assert response.status_code == 422

    run(scenario())


def test_optional_agent_session_protects_loopback_api(monkeypatch):
    monkeypatch.setenv("MODAL_2D_AGENT_TOKEN", "session-secret")

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            unauthorized = await client.get("/health")
            assert unauthorized.status_code == 401
            assert "session-secret" not in unauthorized.text

            authorized = await client.get(
                "/health",
                headers={"X-Modal-2D-Session": "session-secret"},
            )
            assert authorized.status_code == 200

    run(scenario())


def test_openapi_docs_are_disabled():
    async def scenario():
        async with await client_for(create_app(Service())) as client:
            assert (await client.get("/docs")).status_code == 404
            assert (await client.get("/redoc")).status_code == 404

    run(scenario())


def test_artifact_route_exposes_immutable_identity_headers(tmp_path):
    data = b"\x89PNG\r\n\x1a\nbody"
    path = tmp_path / "image.png"
    path.write_bytes(data)

    class ArtifactService(Service):
        def artifact(self, job_id):
            return (
                {
                    "id": "art_abc",
                    "sha256": "a" * 64,
                },
                path,
            )

    async def scenario():
        async with await client_for(create_app(ArtifactService())) as client:
            response = await client.get("/v1/jobs/job_01/artifact")
            assert response.status_code == 200
            assert response.content == data
            assert response.headers["etag"] == f'"{"a" * 64}"'
            assert response.headers["x-artifact-id"] == "art_abc"
            assert response.headers["x-artifact-sha256"] == "a" * 64
            assert response.headers["content-type"].startswith("image/png")

    run(scenario())


def test_ui_is_served_without_session_token(monkeypatch):
    """UI 是静态资源，带不上 session 头；启用 token 后仍必须可导航。"""
    monkeypatch.setenv("MODAL_2D_AGENT_TOKEN", "session-secret")

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            # 根路径重定向到操作台：页面资源用相对路径引用，
            # 直接在 `/` 渲染会让它们解析到 /app.js。
            root = await client.get("/", follow_redirects=False)
            assert root.status_code == 307
            assert root.headers["location"].endswith("/ui/index.html")

            page = await client.get("/ui/index.html")
            assert page.status_code == 200
            assert "modal-2D Agent" in page.text

            for asset in ("/ui/app.js", "/ui/styles.css"):
                response = await client.get(asset)
                assert response.status_code == 200, asset

            # XHR 仍然受保护。
            assert (await client.get("/health")).status_code == 401

    run(scenario())


def test_ui_does_not_echo_session_token(monkeypatch):
    monkeypatch.setenv("MODAL_2D_AGENT_TOKEN", "session-secret")

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            page = await client.get("/ui/index.html")
            assert "session-secret" not in page.text
            for asset in ("/ui/app.js", "/ui/styles.css"):
                assert "session-secret" not in (await client.get(asset)).text

    run(scenario())


def test_ui_assets_are_not_python_source():
    """UI 目录只应包含静态资源，避免 mount 暴露 .py。"""
    from pathlib import Path

    from modal_2d_client.app import UI_DIR

    files = [path.name for path in Path(UI_DIR).iterdir() if path.is_file()]
    assert files, "UI 资源缺失"
    assert not any(name.endswith(".py") for name in files), files


def test_cors_allows_any_origin_by_default(monkeypatch):
    """默认允许任意来源，便于容器/局域网/反向代理访问。"""
    monkeypatch.delenv("MODAL_2D_CORS_ORIGINS", raising=False)

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            response = await client.options(
                "/health",
                headers={
                    "Origin": "http://example.test",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert response.headers["access-control-allow-origin"] == "*"

    run(scenario())


def test_cors_preflight_allows_session_header(monkeypatch):
    monkeypatch.delenv("MODAL_2D_CORS_ORIGINS", raising=False)

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            response = await client.options(
                "/v1/jobs",
                headers={
                    "Origin": "http://example.test",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type,x-modal-2d-session",
                },
            )
            assert response.headers["access-control-allow-origin"] == "*"
            allowed = response.headers["access-control-allow-headers"].lower()
            assert "x-modal-2d-session" in allowed

    run(scenario())


def test_cors_origins_can_be_restricted(monkeypatch):
    monkeypatch.setenv("MODAL_2D_CORS_ORIGINS", "http://a.test, http://b.test")

    async def scenario():
        async with await client_for(create_app(Service())) as client:
            allowed = await client.options(
                "/health",
                headers={
                    "Origin": "http://a.test",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert allowed.headers["access-control-allow-origin"] == "http://a.test"

            denied = await client.options(
                "/health",
                headers={
                    "Origin": "http://evil.test",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert "access-control-allow-origin" not in denied.headers

    run(scenario())


def test_artifact_headers_are_exposed_cross_origin(tmp_path):
    """跨域时前端必须能读到这三个头，否则 SHA-256 校验无法进行。"""
    data = b"\x89PNG\r\n\x1a\nbody"
    path = tmp_path / "image.png"
    path.write_bytes(data)

    class ArtifactService(Service):
        def artifact(self, job_id):
            return ({"id": "art_abc", "sha256": "a" * 64}, path)

    async def scenario():
        async with await client_for(create_app(ArtifactService())) as client:
            response = await client.get(
                "/v1/jobs/job_01/artifact",
                headers={"Origin": "http://example.test"},
            )
            assert response.status_code == 200
            exposed = response.headers["access-control-expose-headers"].lower()
            assert "x-artifact-sha256" in exposed
            assert "x-artifact-id" in exposed
            assert "etag" in exposed

    run(scenario())


def test_ui_assets_are_declared_as_package_data():
    """setuptools 默认不打非 .py 资源；漏配会让安装后 /ui 404。"""
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    )
    package_data = pyproject.get("tool", {}).get("setuptools", {}).get("package-data", {})
    patterns = package_data.get("modal_2d_client", [])
    assert "static/*.html" in patterns
    assert "static/*.css" in patterns
    assert "static/*.js" in patterns


def test_api_accepts_batch_seeds_as_one_job():
    class BatchService(Service):
        def __init__(self):
            self.payload = None

        def submit(self, payload, *, job_id=None):
            self.payload = payload
            return {"id": job_id or "job_batch", "status": "running", "model": payload["model"]}

    service = BatchService()

    async def scenario():
        async with await client_for(create_app(service)) as client:
            response = await client.post(
                "/v1/jobs",
                json={
                    "prompt": "red apple",
                    "seeds": [42, 73, 104, 135],
                    "job_id": "job_batch",
                },
            )
            assert response.status_code == 200
            assert service.payload["seeds"] == [42, 73, 104, 135]
            invalid = await client.post("/v1/jobs", json={"prompt": "x", "seed": 42, "seeds": [73]})
            assert invalid.status_code == 422

    run(scenario())
