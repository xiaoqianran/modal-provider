from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from . import capabilities, modal_session
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


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=4000)
    model: str = "sana-sprint-1.6b"
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    steps: int | None = Field(default=None, ge=1, le=4)
    guidance: float | None = Field(default=None, ge=0, le=20)


def create_app(service: JobService | None = None) -> FastAPI:
    app = FastAPI(title="modal-2D Client Agent", version="0.1.0")

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
    def get_capabilities():
        try:
            return capabilities.document()
        except modal_session.NotConnectedError as exc:
            raise HTTPException(status_code=409, detail="Modal connection required") from exc
        except ContractError as exc:
            raise HTTPException(status_code=502, detail="Incompatible modal-2D capability") from exc

    @app.get("/v1/models")
    def get_models():
        try:
            return {"models": capabilities.public_models()}
        except modal_session.NotConnectedError as exc:
            raise HTTPException(status_code=409, detail="Modal connection required") from exc

    @app.get("/v1/jobs")
    def list_jobs(limit: int = 50):
        return {"jobs": job_service().store.list(max(1, min(limit, 200)))}

    @app.post("/v1/jobs")
    def submit_job(body: GenerateBody):
        try:
            return job_service().submit(body.model_dump(exclude_none=True))
        except modal_session.NotConnectedError as exc:
            raise HTTPException(status_code=409, detail="Modal connection required") from exc
        except ContractError as exc:
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
        except ContractError as exc:
            raise HTTPException(status_code=502, detail="Artifact integrity check failed") from exc
        return FileResponse(
            path,
            media_type="image/png",
            headers={
                "X-Artifact-ID": str(descriptor["id"]),
                "X-Artifact-SHA256": str(descriptor["sha256"]),
            },
        )

    return app


app = create_app()
