from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from ..app import _json_body, _read_bounded_body, build_runtime
from ..errors import ConnectorError
from .auth import StudioAuth
from .service import StudioService


def create_app(service=None, auth=None, *, background=True, persist=None):
    auth = auth or StudioAuth()

    @asynccontextmanager
    async def lifespan(app):
        nonlocal service
        if service is None:
            runtime = build_runtime()
            if os.getenv("STUDIO_CONNECT_MODAL", "1") == "1":
                await runtime.deployments.connect_default_async()
                await runtime.capabilities.connect_all_default_async()
            service = StudioService.configured(runtime, persist=persist)
        if background:
            service.start()
        try:
            yield
        finally:
            if background:
                await run_in_threadpool(service.close)

    app = FastAPI(
        title="Studio API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.exception_handler(ConnectorError)
    async def error(_request, exc):
        return JSONResponse(status_code=exc.status, content=exc.payload())

    @app.middleware("http")
    async def identity(request, call_next):
        if request.url.path != "/health":
            try:
                request.state.owner = await run_in_threadpool(auth.owner, request)
            except ConnectorError as exc:
                return JSONResponse(status_code=exc.status, content=exc.payload())
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health")
    def health():
        return {"ok": True, "service": "studio"}

    @app.get("/api/v1/me")
    def me(request: Request):
        return {"id": request.state.owner, "authMode": auth.mode}

    @app.get("/api/v1/capabilities")
    async def capabilities():
        return await service.hub.capabilities.snapshot_async()

    @app.get("/api/v1/projects")
    def projects(request: Request):
        service._project(request.state.owner, None)
        return {"projects": service.store.list("project", request.state.owner)}

    @app.post("/api/v1/projects", status_code=201)
    async def create_project(request: Request):
        payload = await _json_body(request)
        return {
            "project": await run_in_threadpool(
                service.project, request.state.owner, payload.get("name")
            )
        }

    @app.post("/api/v1/uploads", status_code=201)
    async def upload(request: Request):
        mime = request.headers.get("content-type", "").split(";")[0]
        maximum = 20 * 1024 * 1024 if mime == "image/png" else 90 * 1024 * 1024
        data = await _read_bounded_body(request, maximum)
        asset = await run_in_threadpool(
            service.upload,
            request.state.owner,
            data,
            mime,
            request.query_params.get("name", "Uploaded asset"),
            request.query_params.get("projectId"),
        )
        return {"asset": asset}

    @app.post("/api/v1/jobs", status_code=202)
    async def submit(request: Request):
        payload = await _json_body(request)
        job = await run_in_threadpool(
            service.submit, request.state.owner, payload, request.headers.get("idempotency-key")
        )
        return {"job": job}

    @app.get("/api/v1/jobs")
    def jobs(request: Request):
        return {"jobs": service.store.list("job", request.state.owner)}

    @app.get("/api/v1/jobs/{job_id}")
    def job(job_id: str, request: Request):
        return {"job": service.owned("job", request.state.owner, job_id)}

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request):
        return {"job": service.cancel(request.state.owner, job_id)}

    @app.get("/api/v1/assets")
    def assets(request: Request):
        return {"assets": service.store.list("asset", request.state.owner)}

    @app.get("/api/v1/assets/{asset_id}")
    def asset(asset_id: str, request: Request):
        return {"asset": service.owned("asset", request.state.owner, asset_id)}

    @app.get("/api/v1/assets/{asset_id}/versions")
    def versions(asset_id: str, request: Request):
        source = service.owned("asset", request.state.owner, asset_id)
        return {
            "versions": [
                a
                for a in service.store.list("asset", request.state.owner)
                if a["assetId"] == source["assetId"]
            ]
        }

    @app.get("/api/v1/assets/{asset_id}/content")
    def content(asset_id: str, request: Request):
        artifact, path = service.open_asset(request.state.owner, asset_id)
        return FileResponse(path, media_type=artifact["mime"])

    return app


def main():
    import uvicorn

    host = os.getenv("STUDIO_HOST", "127.0.0.1")
    if os.getenv("STUDIO_AUTH_MODE") == "development" and host not in {"127.0.0.1", "::1"}:
        raise ValueError("Development authentication must bind to loopback")
    uvicorn.run(create_app(), host=host, port=int(os.getenv("STUDIO_PORT", "48125")))
