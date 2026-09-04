from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response

from .artifacts import ArtifactService
from .capabilities import CapabilityRegistry
from .constants import SESSION_PATH, allow_any_origin
from .credentials import CredentialStore
from .deployments import DeploymentService
from .errors import ConnectorError
from .jobs import JobService
from .providers.loader import load_providers
from .sessions import SessionService, normalize_origin
from .storage import Store

_DEFAULT_AGENT_TOKEN = "wangran"
_LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class Runtime:
    store: Store
    capabilities: CapabilityRegistry
    sessions: SessionService
    jobs: JobService
    artifacts: ArtifactService
    deployments: DeploymentService


def build_runtime(store: Store | None = None, *, adapters=None) -> Runtime:
    state = store or Store()
    provider_adapters = adapters if adapters is not None else load_providers()
    deployments = DeploymentService(provider_adapters)
    registry = CapabilityRegistry(state, provider_adapters, deployments)
    artifacts = ArtifactService(state, registry)
    return Runtime(
        store=state,
        capabilities=registry,
        sessions=SessionService(state, registry),
        jobs=JobService(state, registry, artifacts),
        artifacts=artifacts,
        deployments=deployments,
    )


_default_runtime: Runtime | None = None


def runtime() -> Runtime:
    global _default_runtime
    if _default_runtime is None:
        _default_runtime = build_runtime()
    return _default_runtime


def create_app(state: Runtime | None = None) -> FastAPI:
    credentials = CredentialStore()

    async def restore_saved_credentials() -> None:
        if state is not None:
            return
        saved = credentials.load()
        if saved is None:
            return
        target = runtime()
        try:
            await target.deployments.connect_async(saved.token_id, saved.token_secret)
            await target.capabilities.connect_all_async(saved.token_id, saved.token_secret)
        except Exception as exc:
            target.deployments.disconnect()
            target.capabilities.disconnect_all()
            _LOG.warning("无法自动恢复已保存的 Modal 凭据: %s", exc)

    restore_task: asyncio.Task[None] | None = None

    async def stop_credential_restore() -> None:
        nonlocal restore_task
        task, restore_task = restore_task, None
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        nonlocal restore_task
        restore_task = asyncio.create_task(restore_saved_credentials())
        try:
            yield
        finally:
            await stop_credential_restore()

    app = FastAPI(
        title="modal-gen Connector",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

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
            expected = os.environ.get("MODAL_GEN_AGENT_TOKEN") or _DEFAULT_AGENT_TOKEN
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
    async def providers():
        snapshot = await current().capabilities.snapshot_async()
        return {"providers": snapshot["providers"]}

    @app.get("/v1/provider-connections")
    def provider_connections():
        return {"providers": current().capabilities.connections()}

    @app.post("/v1/providers/connect")
    async def connect_providers(request: Request):
        await stop_credential_restore()
        payload = await _json_body(request)
        token_id = payload.get("tokenId")
        token_secret = payload.get("tokenSecret")
        if not isinstance(token_id, str) or not isinstance(token_secret, str):
            raise ConnectorError("PROVIDER_CREDENTIALS_REQUIRED", "Modal credentials 不能为空", 422)
        await current().deployments.connect_async(token_id, token_secret)
        rows = await current().capabilities.connect_all_async(token_id, token_secret)
        if state is None:
            credentials.save(token_id, token_secret)
        return {"providers": rows}

    @app.post("/v1/providers/disconnect")
    async def disconnect_providers():
        await stop_credential_restore()
        current().deployments.disconnect()
        rows = current().capabilities.disconnect_all()
        return {"providers": rows}

    @app.get("/v1/deployments")
    async def deployments(provider: str | None = None, refresh: bool = False):
        return await current().deployments.status_async(provider, force=refresh)

    @app.get("/v1/secrets/huggingface")
    async def huggingface_secret_status():
        if not current().deployments.connected:
            return {"connected": False, "configured": False, "secrets": []}
        return await run_in_threadpool(current().deployments.huggingface_secret_status)

    @app.post("/v1/secrets/huggingface")
    async def save_huggingface_secret(request: Request):
        payload = await _json_body(request)
        token = payload.get("token")
        if not isinstance(token, str):
            raise ConnectorError("HF_TOKEN_REQUIRED", "Hugging Face Token 不能为空", 422)
        return await run_in_threadpool(current().deployments.save_huggingface_token, token)

    @app.get("/v1/deployments/jobs")
    def deployment_jobs(limit: int = 20):
        return current().deployments.deployment_jobs(limit)

    @app.get("/v1/deployments/jobs/{job_id}")
    def deployment_job(job_id: str):
        return {"job": current().deployments.deployment_job(job_id)}

    @app.post("/v1/deployments/deploy")
    async def deploy_runtimes(request: Request):
        payload = await _json_body(request)
        token_id = payload.get("tokenId")
        token_secret = payload.get("tokenSecret")
        if (
            isinstance(token_id, str)
            and isinstance(token_secret, str)
            and token_id
            and token_secret
        ):
            await current().deployments.connect_async(token_id, token_secret)
        provider = payload.get("provider")
        if provider is not None and not isinstance(provider, str):
            raise ConnectorError("DEPLOYMENT_PROVIDER_INVALID", "provider 必须是字符串", 422)
        app_name = payload.get("app")
        if app_name is not None and not isinstance(app_name, str):
            raise ConnectorError("DEPLOYMENT_APP_INVALID", "app 必须是字符串", 422)
        force = payload.get("force", False)
        if not isinstance(force, bool):
            raise ConnectorError("DEPLOYMENT_FORCE_INVALID", "force 必须是布尔值", 422)
        strategy = payload.get("strategy", "rolling")
        if not isinstance(strategy, str):
            raise ConnectorError("DEPLOYMENT_STRATEGY_INVALID", "strategy 必须是字符串", 422)
        environment_name = payload.get("environment")
        if environment_name is not None and not isinstance(environment_name, str):
            raise ConnectorError("DEPLOYMENT_ENV_INVALID", "environment 必须是字符串", 422)
        missing_only = payload.get("missingOnly", False)
        if not isinstance(missing_only, bool):
            raise ConnectorError("DEPLOYMENT_MISSING_ONLY_INVALID", "missingOnly 必须是布尔值", 422)
        job = await run_in_threadpool(
            current().deployments.start_deploy,
            provider,
            app_name=app_name,
            strategy=strategy,
            environment_name=environment_name or None,
            missing_only=missing_only,
            force=force,
        )
        return {"job": job}

    @app.get("/v1/capabilities")
    async def local_capabilities(refresh: bool = False):
        return await current().capabilities.snapshot_async(force_runtime=refresh)

    @app.get("/v1/pairings")
    def pairings():
        return {"pairings": current().store.list_pairings()}

    @app.post("/v1/pairings/{pairing_id}/approve")
    def approve_pairing(pairing_id: str):
        return current().sessions.approve(pairing_id)

    @app.post(SESSION_PATH)
    async def pair_session(request: Request):
        payload = await _json_body(request)
        capability_snapshot = None
        if payload.get("pairingId"):
            capability_snapshot = await current().capabilities.snapshot_async(force_runtime=True)
        return current().sessions.pair(
            payload,
            request_origin=request.headers.get("origin"),
            capability_snapshot=capability_snapshot,
        )

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
        job = await run_in_threadpool(current().jobs.submit, payload, session)
        return {"job": job}

    @app.get("/connector/v1/jobs")
    def list_jobs(
        request: Request,
        status: str | None = None,
        q: str = "",
        limit: int = 25,
        offset: int = 0,
    ):
        session = current().sessions.authorize(
            request.headers.get("authorization"),
            "jobs.read",
            request_origin=request.headers.get("origin"),
        )
        page_limit = max(1, min(limit, 200))
        page_offset = max(0, offset)
        jobs = current().jobs.list(
            session, status=status, q=q, limit=page_limit, offset=page_offset
        )
        total = current().jobs.count(session, status=status, q=q)
        return {
            "jobs": jobs,
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
            "eventCursor": None,
        }

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

    @app.get("/connector/v1/artifacts")
    def list_artifacts(request: Request, mime: str | None = None, limit: int = 12, offset: int = 0):
        session = current().sessions.authorize(
            request.headers.get("authorization"),
            "artifacts.read",
            request_origin=request.headers.get("origin"),
        )
        page_limit = max(1, min(limit, 48))
        page_offset = max(0, offset)
        owner_client = str(session["client_identity"])
        owner_origin = str(session["origin"])
        artifacts = current().artifacts.list(
            owner_client=owner_client,
            owner_origin=owner_origin,
            mime=mime or None,
            limit=page_limit,
            offset=page_offset,
        )
        total = current().artifacts.count(
            owner_client=owner_client, owner_origin=owner_origin, mime=mime or None
        )
        return {
            "artifacts": artifacts,
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
        }

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
