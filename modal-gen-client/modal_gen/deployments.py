from __future__ import annotations

import copy
import importlib
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

import modal
from modal.exception import NotFoundError

from .errors import ConnectorError


@dataclass(frozen=True, slots=True)
class DeploymentTarget:
    provider: str
    app_name: str
    module: str
    revision: str | None = None
    models: tuple[str, ...] = ()
    required: bool = False


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


_DEPLOYMENT_TAG = re.compile(r"^[A-Za-z0-9._-]{1,50}$")


def _validate_revision(revision: str | None) -> None:
    if revision is not None and not _DEPLOYMENT_TAG.fullmatch(revision):
        raise ConnectorError(
            "DEPLOYMENT_REVISION_INVALID",
            "Runtime revision 必须符合 Modal deployment tag 规则",
            500,
        )


class DeploymentService:
    def __init__(
        self,
        adapters=(),
        *,
        targets: tuple[DeploymentTarget, ...] | None = None,
        max_workers: int = 2,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._client: modal.Client | None = None
        self._lock = threading.RLock()
        self._targets_all = (
            targets if targets is not None else self._targets_from_adapters(adapters)
        )
        for target in self._targets_all:
            _validate_revision(target.revision)
        self._target_locks = {
            (target.provider, target.app_name): threading.Lock() for target in self._targets_all
        }
        self._jobs: dict[str, dict[str, object]] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="modal-gen-deploy",
        )

    @staticmethod
    def _targets_from_adapters(adapters) -> tuple[DeploymentTarget, ...]:
        rows: list[DeploymentTarget] = []
        seen: set[tuple[str, str]] = set()
        for adapter in adapters:
            factory = getattr(adapter, "deployment_manifest", None)
            if not callable(factory):
                continue
            manifest = factory()
            provider = str(manifest.get("provider") or getattr(adapter, "id", "")).strip()
            targets = manifest.get("targets")
            if not provider or not isinstance(targets, list):
                continue
            for item in targets:
                if not isinstance(item, dict):
                    continue
                app_name = str(item.get("app") or "").strip()
                module = str(item.get("module") or "").strip()
                key = (provider, app_name)
                if not app_name or not module or key in seen:
                    continue
                revision = str(item.get("revision") or "").strip() or None
                _validate_revision(revision)
                raw_models = item.get("models")
                models = (
                    tuple(str(value) for value in raw_models if isinstance(value, str))
                    if isinstance(raw_models, list)
                    else ()
                )
                rows.append(
                    DeploymentTarget(
                        provider=provider,
                        app_name=app_name,
                        module=module,
                        revision=revision,
                        models=models,
                        required=item.get("required") is True,
                    )
                )
                seen.add(key)
        return tuple(rows)

    def connect(self, token_id: str, token_secret: str) -> None:
        if not token_id.strip() or not token_secret.strip():
            raise ConnectorError("PROVIDER_CREDENTIALS_REQUIRED", "Modal credentials 不能为空", 422)
        client = modal.Client.from_credentials(token_id.strip(), token_secret.strip())
        with self._lock:
            self._client = client

    def disconnect(self) -> None:
        with self._lock:
            self._client = None

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._client is not None

    def _require_client(self) -> modal.Client:
        with self._lock:
            client = self._client
        if client is None:
            raise ConnectorError("DEPLOYMENT_CREDENTIALS_REQUIRED", "请先连接 Modal", 409)
        return client

    def _targets(self, provider: str | None = None) -> tuple[DeploymentTarget, ...]:
        if provider is None or provider == "all":
            return self._targets_all
        selected = tuple(target for target in self._targets_all if target.provider == provider)
        if not selected:
            raise ConnectorError("DEPLOYMENT_PROVIDER_UNKNOWN", f"未知 Provider: {provider}", 422)
        return selected

    def _select_targets(
        self,
        provider: str | None,
        app_name: str | None,
    ) -> tuple[DeploymentTarget, ...]:
        targets = self._targets(provider)
        if app_name is None:
            return targets
        selected = tuple(target for target in targets if target.app_name == app_name)
        if not selected:
            raise ConnectorError("DEPLOYMENT_APP_UNKNOWN", f"未知 Runtime App: {app_name}", 422)
        return selected

    @staticmethod
    def _validate_strategy(strategy: str) -> None:
        if strategy not in {"rolling", "recreate"}:
            raise ConnectorError(
                "DEPLOYMENT_STRATEGY_INVALID", "strategy 必须是 rolling 或 recreate", 422
            )

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
        missing_only: bool = False,
    ) -> dict[str, object]:
        self._validate_strategy(strategy)
        client = self._require_client()
        targets = self._select_targets(provider, app_name)
        if missing_only:
            statuses = {
                target.app_name: self._target_status(target, client)["status"] for target in targets
            }
            targets = tuple(target for target in targets if statuses[target.app_name] == "missing")

        rows: list[dict[str, object]] = []
        for target in targets:
            lock = self._target_locks.setdefault(
                (target.provider, target.app_name), threading.Lock()
            )
            with lock:
                rows.append(
                    self._deploy_target(
                        target,
                        client,
                        strategy=strategy,
                        environment_name=environment_name,
                    )
                )
        return self._summary(rows)

    def _deploy_target(
        self,
        target: DeploymentTarget,
        client: modal.Client,
        *,
        strategy: str,
        environment_name: str | None,
    ) -> dict[str, object]:
        try:
            module = importlib.import_module(target.module)
            app = module.app
            deployed = app.deploy(
                name=target.app_name,
                environment_name=environment_name,
                client=client,
                strategy=strategy,
                tag=target.revision or "",
            )
            if target.revision:
                tags = deployed.get_tags(client=client)
                tags["modal-gen-revision"] = target.revision
                deployed.set_tags(tags, client=client)
            return {
                "provider": target.provider,
                "app": target.app_name,
                "module": target.module,
                "status": "current",
                "expectedRevision": target.revision,
                "deployedRevision": target.revision,
                "models": list(target.models),
                "required": target.required,
            }
        except Exception as exc:
            return {
                "provider": target.provider,
                "app": target.app_name,
                "module": target.module,
                "status": "failed",
                "expectedRevision": target.revision,
                "models": list(target.models),
                "required": target.required,
                "error": str(exc),
            }

    def start_deploy(
        self,
        provider: str | None = None,
        *,
        app_name: str | None = None,
        strategy: str = "rolling",
        environment_name: str | None = None,
        missing_only: bool = False,
    ) -> dict[str, object]:
        self._require_client()
        self._validate_strategy(strategy)
        self._select_targets(provider, app_name)
        job_id = f"dep_{uuid.uuid4().hex}"
        timestamp = _now()
        job: dict[str, object] = {
            "id": job_id,
            "status": "queued",
            "provider": provider or "all",
            "app": app_name,
            "strategy": strategy,
            "environment": environment_name,
            "missingOnly": missing_only,
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = job
        client = self._require_client()
        thread = threading.Thread(
            target=self._run_deployment_job,
            args=(
                job_id,
                client,
                provider,
                app_name,
                strategy,
                environment_name,
                missing_only,
            ),
            name=f"modal-gen-deploy-job-{job_id[-8:]}",
            daemon=True,
        )
        thread.start()
        return self.deployment_job(job_id)

    def _run_deployment_job(
        self,
        job_id: str,
        client: modal.Client,
        provider: str | None,
        app_name: str | None,
        strategy: str,
        environment_name: str | None,
        missing_only: bool,
    ) -> None:
        self._update_job(job_id, status="running")
        try:
            targets = self._select_targets(provider, app_name)
            if missing_only:
                targets = tuple(
                    target
                    for target in targets
                    if self._target_status(target, client)["status"] == "missing"
                )
            self._update_job(
                job_id,
                targets=[
                    {
                        "provider": target.provider,
                        "app": target.app_name,
                        "status": "queued",
                    }
                    for target in targets
                ],
            )
            futures = [
                self._executor.submit(
                    self._deploy_target_for_job,
                    job_id,
                    index,
                    target,
                    client,
                    strategy,
                    environment_name,
                )
                for index, target in enumerate(targets)
            ]
            rows = [future.result() for future in futures]
            result = self._summary(rows)
        except Exception as exc:
            self._update_job(job_id, status="failed", error=str(exc))
            return
        terminal = self._deployment_result_status(result)
        self._update_job(job_id, status=terminal, result=result)

    def _deploy_target_for_job(
        self,
        job_id: str,
        index: int,
        target: DeploymentTarget,
        client: modal.Client,
        strategy: str,
        environment_name: str | None,
    ) -> dict[str, object]:
        self._update_target_job_status(job_id, index, "deploying")
        lock = self._target_locks.setdefault((target.provider, target.app_name), threading.Lock())
        with lock:
            row = self._deploy_target(
                target,
                client,
                strategy=strategy,
                environment_name=environment_name,
            )
        self._update_target_job_status(job_id, index, str(row["status"]), row.get("error"))
        return row

    def _update_target_job_status(
        self,
        job_id: str,
        index: int,
        status: str,
        error: object | None = None,
    ) -> None:
        with self._lock:
            current = self._jobs[job_id]
            targets = copy.deepcopy(current.get("targets") or [])
            if 0 <= index < len(targets):
                targets[index]["status"] = status
                if error:
                    targets[index]["error"] = str(error)
            self._jobs[job_id] = {**current, "targets": targets, "updatedAt": _now()}

    @staticmethod
    def _deployment_result_status(result: dict[str, object]) -> str:
        providers = result.get("providers")
        if not isinstance(providers, list):
            return "failed"
        app_statuses = [
            str(app.get("status"))
            for provider in providers
            if isinstance(provider, dict) and isinstance(provider.get("apps"), list)
            for app in provider["apps"]
            if isinstance(app, dict)
        ]
        if not app_statuses:
            return "succeeded"
        failures = sum(status in {"failed", "error"} for status in app_statuses)
        if failures == 0:
            return "succeeded"
        return "failed" if failures == len(app_statuses) else "partial"

    def _update_job(self, job_id: str, **values: object) -> None:
        with self._lock:
            current = self._jobs[job_id]
            self._jobs[job_id] = {**current, **values, "updatedAt": _now()}

    def deployment_job(self, job_id: str) -> dict[str, object]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ConnectorError("DEPLOYMENT_JOB_NOT_FOUND", "Deployment Job 不存在", 404)
            return copy.deepcopy(job)

    def deployment_jobs(self, limit: int = 20) -> dict[str, object]:
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = sorted(
                self._jobs.values(),
                key=lambda item: str(item.get("createdAt") or ""),
                reverse=True,
            )[:limit]
            return {"jobs": copy.deepcopy(rows)}

    @staticmethod
    def _target_status(target: DeploymentTarget, client: modal.Client) -> dict[str, object]:
        actual_revision = None
        try:
            deployed = modal.App.lookup(target.app_name, client=client)
            tags = deployed.get_tags(client=client)
            actual_revision = tags.get("modal-gen-revision")
            status = (
                "current"
                if target.revision is not None and actual_revision == target.revision
                else "stale"
            )
            error = None
        except NotFoundError as exc:
            status, error = "missing", str(exc)
        except Exception as exc:
            status, error = "error", str(exc)
        row: dict[str, object] = {
            "provider": target.provider,
            "app": target.app_name,
            "module": target.module,
            "status": status,
            "expectedRevision": target.revision,
            "deployedRevision": actual_revision,
            "models": list(target.models),
            "required": target.required,
        }
        if error:
            row["error"] = error
        return row

    @staticmethod
    def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
        result = []
        provider_ids = list(dict.fromkeys(str(row["provider"]) for row in rows))
        for provider in provider_ids:
            items = [row for row in rows if row["provider"] == provider]
            statuses = {str(item["status"]) for item in items}
            status = (
                "current"
                if statuses == {"current"}
                else "error"
                if "error" in statuses
                else "failed"
                if "failed" in statuses
                else "stale"
                if statuses <= {"current", "stale"} and "stale" in statuses
                else "missing"
                if statuses == {"missing"}
                else "partial"
            )
            result.append({"id": provider, "status": status, "apps": items})
        return {"providers": result}
