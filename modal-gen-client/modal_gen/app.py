from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .artifacts import ArtifactService
from .capabilities import CapabilityRegistry
from .constants import SESSION_PATH, allow_any_origin
from .errors import ConnectorError
from .jobs import JobService
from .providers.modal2d import Modal2DAdapter
from .providers.modal3d import Modal3DAdapter
from .sessions import SessionService, normalize_origin
from .storage import Store


@dataclass(slots=True)
class Runtime:
    store: Store
    capabilities: CapabilityRegistry
    sessions: SessionService
    jobs: JobService
    artifacts: ArtifactService


def build_runtime(store: Store | None = None, *, adapters=None) -> Runtime:
    state = store or Store()
    registry = CapabilityRegistry(
        state,
        adapters if adapters is not None else [Modal2DAdapter(), Modal3DAdapter()],
    )
    artifacts = ArtifactService(state, registry)
    return Runtime(
        store=state,
        capabilities=registry,
        sessions=SessionService(state, registry),
        jobs=JobService(state, registry, artifacts),
        artifacts=artifacts,
    )


_default_runtime: Runtime | None = None


def runtime() -> Runtime:
    global _default_runtime
    if _default_runtime is None:
        _default_runtime = build_runtime()
    return _default_runtime


def create_app(state: Runtime | None = None) -> FastAPI:
    app = FastAPI(title="modal-gen Connector", version="0.1.0", docs_url=None, redoc_url=None)

    def current() -> Runtime:
        return state or runtime()

    @app.exception_handler(ConnectorError)
    async def connector_error(_request: Request, exc: ConnectorError):
        return JSONResponse(status_code=exc.status, content=exc.payload())

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        if request.method == "OPTIONS" and request.url.path.startswith("/connector/v1/"):
            return _cors_preflight(request)
        if request.url.path.startswith("/v1/"):
            expected = os.environ.get("MODAL_GEN_AGENT_TOKEN")
            if not expected:
                return JSONResponse(
                    status_code=503,
                    content={"code": "LOCAL_CONTROL_LOCKED", "message": "本地控制 token 未配置"},
                )
            provided = request.headers.get("X-Modal-Gen-Session", "")
            if not hmac.compare_digest(provided, expected):
                return JSONResponse(status_code=401, content={"detail": "本地会话无效"})
        response = await call_next(request)
        if request.url.path.startswith("/connector/v1/"):
            _apply_cors(request, response)
        return response

    @app.get("/health")
    def health():
        return {"ok": True, "connector": current().capabilities.connector}

    @app.get("/v1/providers")
    def providers():
        snapshot = current().capabilities.snapshot()
        return {"providers": snapshot["providers"]}

    @app.get("/v1/capabilities")
    def local_capabilities():
        return current().capabilities.snapshot()

    @app.get("/v1/pairings")
    def pairings():
        return {"pairings": current().store.list_pairings()}

    @app.post("/v1/pairings/{pairing_id}/approve")
    def approve_pairing(pairing_id: str):
        return current().sessions.approve(pairing_id)

    @app.post(SESSION_PATH)
    async def pair_session(request: Request):
        payload = await _json_body(request)
        return current().sessions.pair(payload, request_origin=request.headers.get("origin"))

    @app.delete(SESSION_PATH)
    def revoke_session(request: Request):
        return current().sessions.revoke(
            request.headers.get("authorization"), request_origin=request.headers.get("origin")
        )

    @app.get("/connector/v1/capabilities")
    def connector_capabilities(request: Request):
        session = current().sessions.authorize(
            request.headers.get("authorization"),
            "capabilities.read",
            request_origin=request.headers.get("origin"),
        )
        snapshot = current().capabilities.get(str(session["capability_hash"]))
        if not snapshot:
            raise ConnectorError("CONNECTOR_CAPABILITY_STALE", "Capability snapshot 不存在", 409)
        return snapshot

    @app.post("/connector/v1/jobs")
    async def submit_job(request: Request):
        session = current().sessions.authorize(
            request.headers.get("authorization"),
            "jobs.submit",
            request_origin=request.headers.get("origin"),
        )
        payload = await _json_body(request)
        return {"job": current().jobs.submit(payload, session)}

    @app.get("/connector/v1/jobs")
    def list_jobs(request: Request):
        session = current().sessions.authorize(
            request.headers.get("authorization"),
            "jobs.read",
            request_origin=request.headers.get("origin"),
        )
        jobs = current().jobs.list(session)
        return {"jobs": jobs, "eventCursor": None}

    @app.get("/connector/v1/jobs/{job_id}")
    def get_job(job_id: str, request: Request):
        session = current().sessions.authorize(
            request.headers.get("authorization"),
            "jobs.read",
            request_origin=request.headers.get("origin"),
        )
        return {"job": current().jobs.get(job_id, session)}

    @app.post("/connector/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, request: Request):
        session = current().sessions.authorize(
            request.headers.get("authorization"),
            "jobs.cancel",
            request_origin=request.headers.get("origin"),
        )
        return {"job": current().jobs.cancel(job_id, session)}

    @app.get("/connector/v1/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str, request: Request):
        session = current().sessions.authorize(
            request.headers.get("authorization"),
            "artifacts.read",
            request_origin=request.headers.get("origin"),
        )
        artifact, path = current().artifacts.open(
            artifact_id,
            owner_client=str(session["client_identity"]),
            owner_origin=str(session["origin"]),
        )
        accept = request.headers.get("accept", "*/*")
        if accept not in {"*/*", "application/octet-stream", artifact["mime"]}:
            raise ConnectorError("ARTIFACT_ACCEPT_MISMATCH", "Artifact Accept MIME 不匹配", 406)
        return FileResponse(
            path,
            media_type=str(artifact["mime"]),
            headers={
                "ETag": f'"{artifact["hash"]}"',
                "Cache-Control": "private, immutable",
                "X-Artifact-ID": str(artifact["id"]),
                "X-Artifact-SHA256": str(artifact["hash"]),
            },
        )

    return app


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise ConnectorError("CONNECTOR_REQUEST_INVALID", "请求 JSON 无效", 400) from exc
    if not isinstance(payload, dict):
        raise ConnectorError("CONNECTOR_REQUEST_INVALID", "请求 body 必须是对象", 400)
    return payload


def _cors_origin(request: Request) -> str | None:
    """Returns the Origin echo, `*` in wildcard mode, or None if not allowed."""
    raw_origin = request.headers.get("origin")
    if not raw_origin:
        return None
    if allow_any_origin():
        return "*"
    try:
        return normalize_origin(raw_origin)
    except ConnectorError:
        return None


def _cors_preflight(request: Request) -> Response:
    origin = _cors_origin(request)
    if origin is None:
        try:
            normalize_origin(request.headers.get("origin"))
        except ConnectorError as exc:
            return JSONResponse(status_code=403, content=exc.payload())
        return Response(status_code=204)
    response = Response(status_code=204)
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept"
    response.headers["Access-Control-Max-Age"] = "600"
    response.headers["Vary"] = "Origin"
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


def _apply_cors(request: Request, response: Response) -> None:
    origin = _cors_origin(request)
    if origin is None:
        return
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"


app = create_app()
