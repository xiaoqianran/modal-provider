from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, SecretStr

from . import modal_session, models
from .contracts import ContractError
from .jobs import JobService

_default_service: JobService | None = None


def _jobs() -> JobService:
    global _default_service
    if _default_service is None:
        _default_service = JobService()
    return _default_service


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token_id: SecretStr
    token_secret: SecretStr


def create_app(service: JobService | None = None) -> FastAPI:
    app = FastAPI(title="modal-3D Client", version="0.1.0", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        expected = os.environ.get("MODAL_3D_CLIENT_TOKEN")
        if expected and request.method != "OPTIONS":
            provided = request.headers.get("X-Modal-3D-Session", "")
            if not hmac.compare_digest(provided, expected):
                return JSONResponse(status_code=401, content={"detail": "invalid local session"})
        return await call_next(request)

    def job_service() -> JobService:
        return service or _jobs()

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "modal_connected": modal_session.connected()}

    @app.get("/modal/status")
    def modal_status() -> dict[str, bool]:
        return {"connected": modal_session.connected()}

    @app.post("/modal/connect")
    def modal_connect(body: Credentials) -> dict[str, bool]:
        try:
            modal_session.connect(
                body.token_id.get_secret_value(), body.token_secret.get_secret_value()
            )
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Modal authentication failed") from exc
        return {"connected": True}

    @app.delete("/modal/connect")
    def modal_disconnect() -> dict[str, bool]:
        modal_session.disconnect()
        return {"connected": False}

    @app.get("/v1/capabilities")
    def capabilities():
        try:
            return models.capabilities_document()
        except modal_session.NotConnectedError as exc:
            raise HTTPException(status_code=409, detail="Modal connection required") from exc
        except models.CapabilityError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/v1/models")
    def public_models():
        try:
            return {"models": models.public_models()}
        except modal_session.NotConnectedError as exc:
            raise HTTPException(status_code=409, detail="Modal connection required") from exc
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
            return job_service().submit(
                data, model=model, profile=profile, seed=seed, job_id=job_id
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
            filename=f'{descriptor["id"]}.glb',
            headers={
                "ETag": f'"{descriptor["sha256"]}"',
                "X-Artifact-ID": str(descriptor["id"]),
                "X-Artifact-SHA256": str(descriptor["sha256"]),
            },
        )

    return app


app = create_app()
