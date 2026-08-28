"""启动一个带假后端的 Agent 实例，仅用于 UI 渲染与交互核查。

    python -m tests.dev_stub

它把 capabilities / modal_session / JobService 换成不触网的实现，
其余（路由、中间件、静态挂载、响应头）都是真实的生产代码。
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn  # noqa: E402

from modal_2d_client import app as app_module  # noqa: E402
from modal_2d_client import capabilities as capabilities_module  # noqa: E402
from modal_2d_client import modal_session as session_module  # noqa: E402
from tests.fake_provider import (  # noqa: E402
    FakeArtifacts,
    FakeCapabilities,
    FakeJobService,
    FakeModalSession,
)


def build():
    from pathlib import Path

    artifacts = FakeArtifacts(Path(tempfile.mkdtemp(prefix="modal2d-ui-")))
    app = app_module.create_app(FakeJobService(artifacts))

    # 忠实模拟未连接时 /v1/capabilities 与 /v1/models 的 409 行为，
    # 否则 UI 的错误分支无法在渲染核查中被真实走到。
    @app.middleware("http")
    async def require_modal(request, call_next):
        path = request.url.path
        if path.startswith("/v1/capabilities") or path.startswith("/v1/models"):
            if not FakeModalSession.connected:
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=409, content={"detail": "Modal connection required"}
                )
        return await call_next(request)

    return app


def main() -> None:
    # 让 UI 走完整会话受保护路径：静态资源放行、XHR 仍需头。
    os.environ.setdefault("MODAL_2D_AGENT_TOKEN", "dev-session-token")

    capabilities_module.document = FakeCapabilities.document
    capabilities_module.refresh = FakeCapabilities.refresh
    capabilities_module.public_models = FakeCapabilities.public_models
    capabilities_module.ensure_model = FakeCapabilities.ensure_model

    # FakeModalSession.connected 是单一状态源：
    # UI 的 /modal/*、/v1/* 分支与 FakeJobService 都读它。
    FakeModalSession.connected = True

    def _connected() -> bool:
        return FakeModalSession.connected

    def _connect(token_id: str, token_secret: str) -> None:
        if not token_id or not token_secret:
            raise ValueError("Modal credentials are required")
        FakeModalSession.connected = True

    def _disconnect() -> None:
        FakeModalSession.connected = False

    session_module.connected = _connected
    session_module.connect = _connect
    session_module.disconnect = _disconnect
    session_module.client = FakeModalSession.client
    session_module.NotConnectedError = FakeModalSession.NotConnectedError

    # app.py 在模块导入时已绑定 connected，需替换其引用。
    app_module.modal_session = session_module

    print("dev stub → http://127.0.0.1:3212/  (X-Modal-2D-Session: dev-session-token)")
    uvicorn.run(build(), host="127.0.0.1", port=3212, log_level="warning")


if __name__ == "__main__":
    main()
