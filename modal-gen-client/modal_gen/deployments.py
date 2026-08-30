from __future__ import annotations

import asyncio
import copy
import importlib
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

import modal
from modal._utils.async_utils import synchronizer
from modal.exception import ConnectionError as ModalConnectionError
from modal.exception import InternalError, NotFoundError, ServiceError
from modal.exception import TimeoutError as ModalTimeoutError
from modal_proto import api_pb2

from .errors import ConnectorError
from .weights import WeightProvisioner, WeightSpec

_DEPLOY_RETRYABLE = (
    ModalConnectionError,
    ModalTimeoutError,
    InternalError,
    ServiceError,
    TimeoutError,
)


@dataclass(frozen=True, slots=True)
class DeploymentTarget:
    provider: str
    app_name: str
    module: str
    revision: str | None = None
    models: tuple[str, ...] = ()
    required: bool = False
    weights: tuple[WeightSpec, ...] = ()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _rollover_app(client, app_id: str):
    return await client.stub.AppRollover(api_pb2.AppRolloverRequest(app_id=app_id))


_rollover_app_blocking = synchronizer.create_blocking(_rollover_app)


_DEPLOYMENT_TAG = re.compile(r"^[A-Za-z0-9._-]{1,50}$")


def _validate_revision(revision: str | None) -> None:
    if revision is not None and not _DEPLOYMENT_TAG.fullmatch(revision):
        raise ConnectorError(
            "DEPLOYMENT_REVISION_INVALID",
            "Runtime revision 必须符合 Modal deployment tag 规则",
            500,
        )


def _modal_secret_names(client: modal.Client) -> set[str]:
    return {secret.name for secret in modal.Secret.objects.list(client=client)}


def _upsert_modal_secret(name: str, token: str, client: modal.Client, *, exists: bool) -> None:
    values = {"HF_TOKEN": token}
    if exists:
        modal.Secret.from_name(name, client=client).update(values)
    else:
        modal.Secret.objects.create(name, values, client=client)


class DeploymentService:
    def __init__(
        self,
        adapters=(),
        *,
        targets: tuple[DeploymentTarget, ...] | None = None,
        max_workers: int = 2,
        max_attempts: int = 2,
        retry_backoff_s: float = 0.5,
        readiness_ttl_s: float = 10.0,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_backoff_s < 0:
            raise ValueError("retry_backoff_s must be non-negative")
        if readiness_ttl_s < 0:
            raise ValueError("readiness_ttl_s must be non-negative")
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
        self._weights = WeightProvisioner()
        self._jobs: dict[str, dict[str, object]] = {}
        self._active_requests: dict[tuple[object, ...], str] = {}
        self._job_request_keys: dict[str, tuple[object, ...]] = {}
        self._max_attempts = max_attempts
        self._retry_backoff_s = retry_backoff_s
        self._readiness_ttl_s = readiness_ttl_s
        self._readiness_cache: dict[
            tuple[str | None, str | None], tuple[float, dict[str, object]]
        ] = {}
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
                raw_weights = item.get("weights", [])
                if not isinstance(raw_weights, list):
                    raise ConnectorError(
                        "DEPLOYMENT_MANIFEST_INVALID", "Runtime weights 必须是数组", 500
                    )
                try:
                    weights = tuple(
                        WeightSpec.from_manifest(value, default_module=module)
                        for value in raw_weights
                    )
                except ValueError as exc:
                    raise ConnectorError("DEPLOYMENT_MANIFEST_INVALID", str(exc), 500) from exc
                rows.append(
                    DeploymentTarget(
                        provider=provider,
                        app_name=app_name,
                        module=module,
                        revision=revision,
                        models=models,
                        required=item.get("required") is True,
                        weights=weights,
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

    async def connect_async(self, token_id: str, token_secret: str) -> None:
        if not token_id.strip() or not token_secret.strip():
            raise ConnectorError("PROVIDER_CREDENTIALS_REQUIRED", "Modal credentials 不能为空", 422)
        client = await modal.Client.from_credentials.aio(token_id.strip(), token_secret.strip())
        with self._lock:
            self._client = client
            self._readiness_cache.clear()

    def disconnect(self) -> None:
        with self._lock:
            self._client = None
            self._readiness_cache.clear()

    def huggingface_secret_status(self) -> dict[str, object]:
        client = self._require_client()
        names = _modal_secret_names(client)
        managed = ("huggingface", "hyworld2-hf")
        rows = [{"name": name, "exists": name in names} for name in managed]
        return {
            "connected": True,
            "configured": all(item["exists"] for item in rows),
            "secrets": rows,
        }

    def save_huggingface_token(self, token: str) -> dict[str, object]:
        value = token.strip()
        if not value:
            raise ConnectorError("HF_TOKEN_REQUIRED", "Hugging Face Token 不能为空", 422)
        if len(value) > 32768:
            raise ConnectorError("HF_TOKEN_TOO_LONG", "Hugging Face Token 过长", 422)
        client = self._require_client()
        existing = _modal_secret_names(client)
        for name in ("huggingface", "hyworld2-hf"):
            _upsert_modal_secret(name, value, client, exists=name in existing)
        return self.huggingface_secret_status()

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

    async def status_async(
        self,
        provider: str | None = None,
        *,
        environment_name: str | None = None,
        force: bool = False,
    ) -> dict[str, object]:
        targets = self._targets(provider)
        with self._lock:
            client = self._client
        if client is None:
            return self._disconnected_summary(targets)

        key = (provider, environment_name)
        now = time.monotonic()
        with self._lock:
            cached = self._readiness_cache.get(key)
            if not force and cached is not None and cached[0] > now:
                return copy.deepcopy(cached[1])

        rows = list(
            await asyncio.gather(
                *(self._target_status_async(target, client, environment_name) for target in targets)
            )
        )
        result = {"connected": True, **self._summary(rows)}
        with self._lock:
            self._readiness_cache[key] = (
                time.monotonic() + self._readiness_ttl_s,
                copy.deepcopy(result),
            )
        return result

    def _invalidate_readiness_cache(self) -> None:
        with self._lock:
            self._readiness_cache.clear()

    def cached_status(
        self,
        provider: str | None = None,
        *,
        environment_name: str | None = None,
    ) -> dict[str, object] | None:
        key = (provider, environment_name)
        now = time.monotonic()
        with self._lock:
            cached = self._readiness_cache.get(key)
            if cached is None or cached[0] <= now:
                return None
            return copy.deepcopy(cached[1])

    @staticmethod
    def _disconnected_summary(
        targets: tuple[DeploymentTarget, ...],
    ) -> dict[str, object]:
        providers: list[dict[str, object]] = []
        for provider in dict.fromkeys(target.provider for target in targets):
            apps = [
                {
                    "provider": target.provider,
                    "app": target.app_name,
                    "module": target.module,
                    "status": "disconnected",
                    "expectedRevision": target.revision,
                    "deployedRevision": None,
                    "models": list(target.models),
                    "required": target.required,
                }
                for target in targets
                if target.provider == provider
            ]
            providers.append({"id": provider, "status": "disconnected", "apps": apps})
        return {"connected": False, "providers": providers}

    def deploy(
        self,
        provider: str | None = None,
        *,
        app_name: str | None = None,
        strategy: str = "rolling",
        environment_name: str | None = None,
        missing_only: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        self._validate_strategy(strategy)
        if force and missing_only:
            raise ConnectorError(
                "DEPLOYMENT_MODE_CONFLICT",
                "force 与 missingOnly 不能同时启用",
                422,
            )
        client = self._require_client()
        targets = self._select_targets(provider, app_name)
        if missing_only:
            statuses = {
                target.app_name: self._target_status(target, client, environment_name)["status"]
                for target in targets
            }
            targets = tuple(target for target in targets if statuses[target.app_name] == "missing")

        rows: list[dict[str, object]] = []
        for target in targets:
            lock = self._target_locks.setdefault(
                (target.provider, target.app_name), threading.Lock()
            )
            with lock:
                rows.append(
                    self._deploy_target_with_retry(
                        target,
                        client,
                        strategy=strategy,
                        environment_name=environment_name,
                        force=force,
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
        on_phase=None,
    ) -> dict[str, object]:
        try:
            weights = self._weights.ensure(
                target.app_name,
                target.weights,
                client,
                environment_name,
                on_phase=on_phase,
            )
            if on_phase is not None:
                on_phase("deploying")
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
                "weights": weights,
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
                "retryable": isinstance(exc, _DEPLOY_RETRYABLE),
            }

    def _rollover_target(
        self,
        target: DeploymentTarget,
        client: modal.Client,
        *,
        environment_name: str | None,
        on_phase=None,
    ) -> dict[str, object]:
        """Refresh containers for an already-current deployment without rebuilding it."""
        if on_phase is not None:
            on_phase("redeploying")
        deployed = modal.App.lookup(
            target.app_name,
            client=client,
            environment_name=environment_name,
        )

        _rollover_app_blocking(client, deployed.app_id)
        return {
            "provider": target.provider,
            "app": target.app_name,
            "module": target.module,
            "status": "current",
            "expectedRevision": target.revision,
            "deployedRevision": target.revision,
            "models": list(target.models),
            "required": target.required,
            "action": "rollover",
        }

    def _deploy_target_with_retry(
        self,
        target: DeploymentTarget,
        client: modal.Client,
        *,
        strategy: str,
        environment_name: str | None,
        force: bool = False,
        on_attempt=None,
        on_phase=None,
    ) -> dict[str, object]:
        last: dict[str, object] | None = None
        for attempt in range(1, self._max_attempts + 1):
            if on_attempt is not None:
                on_attempt(attempt)
            current = self._target_status(target, client, environment_name) if force else None
            if (
                current is not None
                and current.get("status") == "current"
                and current.get("runnable")
            ):
                try:
                    last = self._rollover_target(
                        target,
                        client,
                        environment_name=environment_name,
                        on_phase=on_phase,
                    )
                except Exception as exc:
                    last = {
                        "provider": target.provider,
                        "app": target.app_name,
                        "module": target.module,
                        "status": "failed",
                        "expectedRevision": target.revision,
                        "models": list(target.models),
                        "required": target.required,
                        "error": str(exc),
                        "retryable": isinstance(exc, _DEPLOY_RETRYABLE),
                        "action": "rollover",
                    }
            else:
                last = self._deploy_target(
                    target,
                    client,
                    strategy=strategy,
                    environment_name=environment_name,
                    on_phase=on_phase,
                )
            last["attempts"] = attempt
            if last.get("status") != "failed" or last.get("retryable") is not True:
                return last
            if attempt < self._max_attempts and self._retry_backoff_s:
                time.sleep(self._retry_backoff_s * attempt)
        assert last is not None
        return last

    def start_deploy(
        self,
        provider: str | None = None,
        *,
        app_name: str | None = None,
        strategy: str = "rolling",
        environment_name: str | None = None,
        missing_only: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        self._require_client()
        self._validate_strategy(strategy)
        if force and missing_only:
            raise ConnectorError(
                "DEPLOYMENT_MODE_CONFLICT",
                "force 与 missingOnly 不能同时启用",
                422,
            )
        self._select_targets(provider, app_name)
        self._invalidate_readiness_cache()
        request_key = (provider, app_name, strategy, environment_name, missing_only, force)
        with self._lock:
            existing_id = self._active_requests.get(request_key)
            if existing_id is not None:
                existing = self._jobs.get(existing_id)
                if existing is not None and existing.get("status") in {"queued", "running"}:
                    return copy.deepcopy(existing)
                self._active_requests.pop(request_key, None)
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
            "force": force,
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._active_requests[request_key] = job_id
            self._job_request_keys[job_id] = request_key
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
                force,
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
        force: bool,
    ) -> None:
        self._update_job(job_id, status="running")
        try:
            targets = self._select_targets(provider, app_name)
            if missing_only:
                targets = tuple(
                    target
                    for target in targets
                    if self._target_status(target, client, environment_name)["status"] == "missing"
                )
            self._update_job(
                job_id,
                targets=[
                    {
                        "provider": target.provider,
                        "app": target.app_name,
                        "status": "queued",
                        "force": force,
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
                    force,
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
        self._invalidate_readiness_cache()

    def _deploy_target_for_job(
        self,
        job_id: str,
        index: int,
        target: DeploymentTarget,
        client: modal.Client,
        strategy: str,
        environment_name: str | None,
        force: bool,
    ) -> dict[str, object]:
        lock = self._target_locks.setdefault((target.provider, target.app_name), threading.Lock())

        def on_attempt(attempt: int) -> None:
            status = "preparing" if attempt == 1 else "retrying"
            self._update_target_job_status(job_id, index, status, attempts=attempt)

        def on_phase(status: str) -> None:
            self._update_target_job_status(job_id, index, status)

        with lock:
            row = self._deploy_target_with_retry(
                target,
                client,
                strategy=strategy,
                environment_name=environment_name,
                force=force,
                on_attempt=on_attempt,
                on_phase=on_phase,
            )
        self._update_target_job_status(
            job_id,
            index,
            str(row["status"]),
            row.get("error"),
            attempts=int(row.get("attempts") or 1),
        )
        return row

    def _update_target_job_status(
        self,
        job_id: str,
        index: int,
        status: str,
        error: object | None = None,
        attempts: int | None = None,
    ) -> None:
        with self._lock:
            current = self._jobs[job_id]
            targets = copy.deepcopy(current.get("targets") or [])
            if 0 <= index < len(targets):
                targets[index]["status"] = status
                if error:
                    targets[index]["error"] = str(error)
                elif "error" in targets[index]:
                    targets[index].pop("error", None)
                if attempts is not None:
                    targets[index]["attempts"] = attempts
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
            updated = {**current, **values, "updatedAt": _now()}
            self._jobs[job_id] = updated
            if updated.get("status") in {"succeeded", "partial", "failed"}:
                request_key = self._job_request_keys.pop(job_id, None)
                if request_key is not None and self._active_requests.get(request_key) == job_id:
                    self._active_requests.pop(request_key, None)

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

    async def _target_status_async(
        self,
        target: DeploymentTarget,
        client: modal.Client,
        environment_name: str | None = None,
    ) -> dict[str, object]:
        actual_revision = None
        try:
            deployed = await modal.App.lookup.aio(
                target.app_name,
                client=client,
                environment_name=environment_name,
            )
            tags = await deployed.get_tags.aio(client=client)
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
        weights = None
        weight_error = None
        if status in {"current", "stale"} and target.weights:
            try:
                weights = await self._weights.status_async(target.weights, client, environment_name)
                if weights["status"] != "ready":
                    weight_error = "required model weights are missing"
            except Exception as exc:
                weight_error = str(exc)
        weights_ready = not target.weights or (
            isinstance(weights, dict) and weights.get("status") == "ready"
        )
        row: dict[str, object] = {
            "provider": target.provider,
            "app": target.app_name,
            "module": target.module,
            "status": status,
            "expectedRevision": target.revision,
            "deployedRevision": actual_revision,
            "models": list(target.models),
            "required": target.required,
            "runnable": status == "current" and weights_ready,
        }
        if weights is not None:
            row["weights"] = weights
        if weight_error:
            row["weightError"] = weight_error
        if error:
            row["error"] = error
        return row

    def _target_status(
        self,
        target: DeploymentTarget,
        client: modal.Client,
        environment_name: str | None = None,
    ) -> dict[str, object]:
        actual_revision = None
        try:
            deployed = modal.App.lookup(
                target.app_name,
                client=client,
                environment_name=environment_name,
            )
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
        weights = None
        weight_error = None
        if status in {"current", "stale"} and target.weights:
            try:
                weights = self._weights.status(target.weights, client, environment_name)
                if weights["status"] != "ready":
                    weight_error = "required model weights are missing"
            except Exception as exc:
                weight_error = str(exc)
        weights_ready = not target.weights or (
            isinstance(weights, dict) and weights.get("status") == "ready"
        )
        row: dict[str, object] = {
            "provider": target.provider,
            "app": target.app_name,
            "module": target.module,
            "status": status,
            "expectedRevision": target.revision,
            "deployedRevision": actual_revision,
            "models": list(target.models),
            "required": target.required,
            "runnable": status == "current" and weights_ready,
        }
        if weights is not None:
            row["weights"] = weights
        if weight_error:
            row["weightError"] = weight_error
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
