from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, SecretStr

from . import constants, demo, modal_session, models
from .contracts import ContractError
from .jobs import JobService
from .session import default_session_token, session_token_matches

_default_service: JobService | None = None
_demo_service: object | None = None

_PACKAGE_DIR = Path(__file__).resolve().parent


def _demo_enabled() -> bool:
    return os.environ.get("MODAL_3D_CLIENT_DEMO") == "1"


def _jobs() -> JobService:
    global _default_service
    if _default_service is None:
        _default_service = JobService()
    return _default_service


def _service(service: JobService | None) -> JobService | object:
    global _demo_service
    if service is not None:
        return service
    if _demo_enabled():
        if _demo_service is None:
            _demo_service = demo.DemoJobService()
        return _demo_service
    return _jobs()


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token_id: SecretStr
    token_secret: SecretStr


def create_app(service: JobService | None = None) -> FastAPI:
    app = FastAPI(title="modal-3D Client", version="0.1.0", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        expected = default_session_token()
        path = request.url.path
        is_ui = path == "/ui/config" or path.startswith("/ui/") or path == "/ui"
        if expected and request.method != "OPTIONS" and not is_ui:
            provided = request.headers.get("X-Modal-3D-Session", "")
            if not session_token_matches(provided, expected):
                return JSONResponse(status_code=401, content={"detail": "invalid local session"})
        return await call_next(request)

    def job_service():
        return _service(service)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "modal_connected": modal_session.connected()}

    @app.get("/modal/status")
    def modal_status() -> dict[str, bool]:
        return {"connected": modal_session.connected()}

    @app.post("/modal/connect")
    def modal_connect(body: Credentials) -> dict[str, bool]:
        if _demo_enabled():
            return {"connected": True}
        try:
            modal_session.connect(
                body.token_id.get_secret_value(), body.token_secret.get_secret_value()
            )
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Modal authentication failed") from exc
        return {"connected": True}

    @app.delete("/modal/connect")
    def modal_disconnect() -> dict[str, bool]:
        if not _demo_enabled():
            modal_session.disconnect()
        return {"connected": _demo_enabled() or modal_session.connected()}

    @app.get("/v1/capabilities")
    def capabilities():
        if _demo_enabled():
            return demo.capability_document()
        try:
            # Capabilities are a local static document; there is no gateway to
            # discover them from and no Modal session required to read them.
            return models.capabilities_document()
        except models.CapabilityError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/v1/models")
    def public_models():
        if _demo_enabled():
            return {"models": [dict(m) for m in demo.capability_document()["models"]]}
        try:
            return {"models": models.public_models()}
        except models.CapabilityError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/v1/jobs")
    def list_jobs(limit: int = 50):
        return {"jobs": job_service().store.list(max(1, min(limit, 200)))}

    @app.post("/v1/jobs")
    async def submit_job(
        file: Annotated[UploadFile, File()],
        model: Annotated[str, Form()],
        profile: Annotated[str, Form()] = "recommended",
        seed: Annotated[int, Form()] = 42,
        job_id: Annotated[str | None, Form()] = None,
    ):
        try:
            data = await file.read()
            return await run_in_threadpool(
                job_service().submit,
                data,
                model=model,
                profile=profile,
                seed=seed,
                job_id=job_id,
            )
        except modal_session.NotConnectedError as exc:
            raise HTTPException(status_code=409, detail="Modal connection required") from exc
        except (ContractError, models.CapabilityError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return job_service().poll(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.delete("/v1/jobs/{job_id}")
    def cancel_job(job_id: str):
        try:
            return job_service().cancel(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/v1/jobs/{job_id}/artifact")
    def get_artifact(job_id: str):
        try:
            descriptor, path = job_service().artifact(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail="Job artifact is not ready") from exc
        except (ContractError, FileNotFoundError) as exc:
            raise HTTPException(status_code=502, detail="Artifact integrity check failed") from exc
        return FileResponse(
            path,
            media_type="model/gltf-binary",
            filename=f"{descriptor['id']}.glb",
            headers={
                "ETag": f'"{descriptor["sha256"]}"',
                "X-Artifact-ID": str(descriptor["id"]),
                "X-Artifact-SHA256": str(descriptor["sha256"]),
            },
        )

    @app.get("/ui/config")
    def ui_config():
        return {
            "require_token": bool(default_session_token()),
            "demo": os.environ.get("MODAL_3D_CLIENT_DEMO") == "1",
            "source": {
                "mediaTypes": list(constants.SOURCE_MEDIA_TYPES),
                "maxBytes": constants.SOURCE_MAX_BYTES,
            },
        }

    def _allow_origin(request: Request) -> str:
        # Any origin is allowed. Set MODAL_3D_CLIENT_ORIGIN to a single origin
        # to narrow this down (returns "*" to everything else otherwise).
        configured = os.environ.get("MODAL_3D_CLIENT_ORIGIN", "").strip().rstrip("/")
        if not configured:
            return "*"
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") == configured:
            return origin
        return "*"

    @app.middleware("http")
    async def cors(request: Request, call_next):
        origin = _allow_origin(request)
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-Modal-3D-Session",
        }
        if request.method == "OPTIONS":
            # 204 must carry no body; a JSONResponse with content would break
            # the declared Content-Length.
            return Response(status_code=204, headers=headers)
        response = await call_next(request)
        for key, value in headers.items():
            response.headers[key] = value
        response.headers["Vary"] = "Origin"
        return response

    return app


def mount_ui(app: FastAPI) -> None:
    static_dir = _PACKAGE_DIR / "static"
    if not static_dir.is_dir():
        return
    app.mount("/ui", StaticFiles(directory=str(static_dir), html=True), name="ui")


app = create_app()
mount_ui(app)
