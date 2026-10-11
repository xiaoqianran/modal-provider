from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from . import capabilities, modal_session
from .contracts import ContractError
from .jobs import JobService

UI_DIR = Path(__file__).parent / "static"
UI_ROOT = "/ui"
UI_INDEX = UI_DIR / "index.html"

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
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    seeds: list[int] | None = Field(default=None, min_length=1, max_length=8)
    guidance: float | None = Field(default=None, ge=0, le=20)
    job_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,160}$")


def _cors_origins() -> list[str]:
    """解析 MODAL_2D_CORS_ORIGINS（逗号分隔）。

    默认 "*"：允许任意来源访问，配合 0.0.0.0 监听便于容器/局域网/反向代理。
    需要收窄时设置该变量为具体来源列表即可。
    """
    raw = os.environ.get("MODAL_2D_CORS_ORIGINS", "*")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["*"]


def create_app(service: JobService | None = None) -> FastAPI:
    app = FastAPI(
        title="modal-2D Client Agent",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["ETag", "X-Artifact-ID", "X-Artifact-SHA256"],
    )

    def is_ui_request(path: str) -> bool:
        # UI 是静态资源，带不上 session 头。放行入口与静态资源，
        # 其发出的 XHR 调用走 /v1 与 /modal，仍然受保护。
        return path == "/" or path == UI_ROOT or path.startswith(f"{UI_ROOT}/")

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        expected = os.environ.get("MODAL_2D_AGENT_TOKEN")
        if expected and request.method != "OPTIONS":
            if not is_ui_request(request.url.path):
                provided = request.headers.get("X-Modal-2D-Session", "")
                if not hmac.compare_digest(provided, expected):
                    return JSONResponse(status_code=401, content={"detail": "本地会话无效"})
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
        capabilities.refresh()
        return {"connected": True}

    @app.delete("/modal/connect")
    def modal_disconnect() -> dict[str, bool]:
        modal_session.disconnect()
        return {"connected": False}

    @app.get("/v1/capabilities")
    def get_capabilities():
        return capabilities.document(refresh_remote=False)

    @app.get("/v1/models")
    def get_models():
        return {"models": capabilities.public_models()}

    @app.get("/v1/jobs")
    def list_jobs(limit: int = 50):
        return {"jobs": job_service().store.list(max(1, min(limit, 200)))}

    @app.post("/v1/jobs")
    def submit_job(body: GenerateBody):
        try:
            payload = body.model_dump(exclude={"job_id"}, exclude_none=True)
            if body.seed is not None and body.seeds is not None:
                raise ContractError("seed and seeds are mutually exclusive")
            if body.seeds is not None and len(set(body.seeds)) != len(body.seeds):
                raise ContractError("seeds must be unique")
            return job_service().submit(payload, job_id=body.job_id)
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

    @app.get("/v1/jobs/{job_id}/artifacts/{index}")
    def get_batch_artifact(job_id: str, index: int):
        try:
            descriptor, path = job_service().artifact(job_id, index=index)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        except IndexError as exc:
            raise HTTPException(status_code=404, detail="Artifact index not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail="Job artifact is not ready") from exc
        except ContractError as exc:
            raise HTTPException(status_code=502, detail="Artifact integrity check failed") from exc
        return FileResponse(
            path,
            media_type="image/png",
            headers={
                "ETag": f'"{descriptor["sha256"]}"',
                "X-Artifact-ID": str(descriptor["id"]),
                "X-Artifact-SHA256": str(descriptor["sha256"]),
            },
        )

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
                "ETag": f'"{descriptor["sha256"]}"',
                "X-Artifact-ID": str(descriptor["id"]),
                "X-Artifact-SHA256": str(descriptor["sha256"]),
            },
        )

    @app.get("/", include_in_schema=False)
    def index():
        """根路径重定向到操作台。

        重定向而非直接返回 HTML：页面资源用相对路径引用，
        直接在 `/` 渲染会让它们解析到错误的 `/app.js`。
        """
        return RedirectResponse(url=f"{UI_ROOT}/index.html", status_code=307)

    if UI_INDEX.is_file():
        app.mount(
            UI_ROOT,
            StaticFiles(directory=UI_DIR, check_dir=False),
            name="ui",
        )

    return app


app = create_app()
