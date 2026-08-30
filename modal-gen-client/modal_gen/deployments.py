from __future__ import annotations

import importlib
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import modal
from modal.exception import NotFoundError

from .errors import ConnectorError


@dataclass(frozen=True, slots=True)
class DeploymentTarget:
    provider: str
    app_name: str
    module: str


TARGETS: tuple[DeploymentTarget, ...] = (
    DeploymentTarget("modal-2d", "modal-2d", "modal_2d.app"),
    DeploymentTarget("modal-2d", "modal-2d-sana-sprint", "modal_2d.workers.sana_sprint"),
    DeploymentTarget("modal-2d", "modal-2d-qwen-image-2512", "modal_2d.workers.qwen_image_2512"),
    DeploymentTarget("modal-2d", "modal-2d-z-image-turbo", "modal_2d.workers.z_image_turbo"),
    DeploymentTarget("modal-2d", "modal-2d-hidream-o1", "modal_2d.workers.hidream_o1"),
    DeploymentTarget("modal-3d", "modal-3d-rembg", "modal_3d.rembg_worker"),
    DeploymentTarget("modal-3d", "modal-3d-fastsam3d", "modal_3d.fastsam3d_plus_plus"),
    DeploymentTarget("modal-3d", "modal-3d-hunyuan", "modal_3d.hunyuan2_1_plus_plus"),
    DeploymentTarget(
        "modal-3d", "modal-3d-hermit-trellis2-plus-plus", "modal_3d.hermit_trellis2_plus_plus"
    ),
    DeploymentTarget("modal-3d", "modal-3d-pixal3d", "modal_3d.pixal3d"),
)


class DeploymentService:
    def __init__(self) -> None:
        self._client: modal.Client | None = None
        repo_root = Path(__file__).resolve().parents[2]
        self._source_roots = (repo_root / "modal-2D", repo_root / "modal-3D")
        self._lock = threading.RLock()

    def connect(self, token_id: str, token_secret: str) -> None:
        if not token_id.strip() or not token_secret.strip():
            raise ConnectorError("PROVIDER_CREDENTIALS_REQUIRED", "Modal credentials 不能为空", 422)
        self._client = modal.Client.from_credentials(token_id.strip(), token_secret.strip())

    def disconnect(self) -> None:
        self._client = None

    def _require_client(self) -> modal.Client:
        if self._client is None:
            raise ConnectorError("DEPLOYMENT_CREDENTIALS_REQUIRED", "请先连接 Modal", 409)
        return self._client

    @staticmethod
    def _targets(provider: str | None = None) -> tuple[DeploymentTarget, ...]:
        if provider is None or provider == "all":
            return TARGETS
        selected = tuple(target for target in TARGETS if target.provider == provider)
        if not selected:
            raise ConnectorError("DEPLOYMENT_PROVIDER_UNKNOWN", f"未知 Provider: {provider}", 422)
        return selected

    def status(self, provider: str | None = None) -> dict[str, object]:
        client = self._require_client()
        rows = [self._target_status(target, client) for target in self._targets(provider)]
        return self._summary(rows)

    def deploy(
        self,
        provider: str | None = None,
        *,
        app_name: str | None = None,
        strategy: str = "rolling",
        environment_name: str | None = None,
    ) -> dict[str, object]:
        if strategy not in {"rolling", "recreate"}:
            raise ConnectorError(
                "DEPLOYMENT_STRATEGY_INVALID", "strategy 必须是 rolling 或 recreate", 422
            )
        client = self._require_client()
        rows: list[dict[str, object]] = []
        with self._lock:
            targets = self._targets(provider)
            if app_name is not None:
                targets = tuple(target for target in targets if target.app_name == app_name)
                if not targets:
                    raise ConnectorError(
                        "DEPLOYMENT_APP_UNKNOWN", f"未知 Runtime App: {app_name}", 422
                    )
            for target in targets:
                try:
                    self._ensure_source_paths()
                    module = importlib.import_module(target.module)
                    app = module.app
                    app.deploy(
                        name=target.app_name,
                        environment_name=environment_name,
                        client=client,
                        strategy=strategy,
                    )
                    rows.append(
                        {
                            "provider": target.provider,
                            "app": target.app_name,
                            "module": target.module,
                            "status": "deployed",
                        }
                    )
                except Exception as exc:
                    rows.append(
                        {
                            "provider": target.provider,
                            "app": target.app_name,
                            "module": target.module,
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
                    break
        return self._summary(rows)

    def _ensure_source_paths(self) -> None:
        missing = [str(path) for path in self._source_roots if not path.is_dir()]
        if missing:
            raise ConnectorError(
                "DEPLOYMENT_SOURCE_MISSING",
                "缺少 Modal Runtime 源码: " + ", ".join(missing),
                409,
            )
        for path in reversed(self._source_roots):
            value = str(path)
            if value not in sys.path:
                sys.path.insert(0, value)

    @staticmethod
    def _target_status(target: DeploymentTarget, client: modal.Client) -> dict[str, object]:
        try:
            modal.App.lookup(target.app_name, client=client)
            status, error = "deployed", None
        except NotFoundError as exc:
            status, error = "missing", str(exc)
        except Exception as exc:
            status, error = "error", str(exc)
        row: dict[str, object] = {
            "provider": target.provider,
            "app": target.app_name,
            "module": target.module,
            "status": status,
        }
        if error:
            row["error"] = error
        return row

    @staticmethod
    def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
        result = []
        for provider in ("modal-2d", "modal-3d"):
            items = [row for row in rows if row["provider"] == provider]
            if not items:
                continue
            statuses = {str(item["status"]) for item in items}
            status = (
                "deployed"
                if statuses == {"deployed"}
                else "failed"
                if "failed" in statuses
                else "partial"
                if "deployed" in statuses
                else "missing"
            )
            result.append({"id": provider, "status": status, "apps": items})
        return {"providers": result}
