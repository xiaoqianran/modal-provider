from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from .artifacts import ArtifactService
from .capabilities import CapabilityRegistry, iso
from .errors import ConnectorError, ProviderError
from .identity import safe_json, verify_request_identity
from .providers.base import ProviderContext, ProviderJob
from .storage import Store

_TERMINAL = {"succeeded", "failed", "cancelled", "expired"}
_ALLOWED_TRANSITIONS = {
    "accepted": {"queued", "running", "connection_required", "cancel_requested", *_TERMINAL},
    "queued": {"running", "connection_required", "cancel_requested", *_TERMINAL},
    "running": {"connection_required", "cancel_requested", *_TERMINAL},
    "connection_required": {"accepted", "queued", "running", "cancel_requested", *_TERMINAL},
    "cancel_requested": {"connection_required", *_TERMINAL},
}
_SAFE_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


class JobService:
    def __init__(
        self,
        store: Store,
        capabilities: CapabilityRegistry,
        artifacts: ArtifactService,
    ) -> None:
        self.store = store
        self.capabilities = capabilities
        self.artifacts = artifacts
        self._submit_locks = tuple(threading.Lock() for _ in range(64))

    def submit(self, payload: dict[str, Any], session: dict[str, object]) -> dict[str, object]:
        verify_request_identity(payload)
        snapshot = self._session_snapshot(session)
        provider_id = str(payload.get("provider") or "").strip()
        operation = str(payload.get("operation") or "").strip()
        resolved = self.capabilities.capability(snapshot, provider_id, operation)
        provider = resolved["provider"]
        capability = resolved["capability"]
        self._validate_submit_contract(payload, provider, capability, session)

        owner_client = str(session["client_identity"])
        owner_origin = str(session["origin"])
        idempotency = str(payload["idempotencyKey"])
        lock = self._submit_locks[hash(idempotency) % len(self._submit_locks)]
        with lock:
            return self._submit_once(
                payload,
                owner_client=owner_client,
                owner_origin=owner_origin,
                provider_id=provider_id,
                operation=operation,
                idempotency=idempotency,
            )

    def _submit_once(
        self,
        payload: dict[str, Any],
        *,
        owner_client: str,
        owner_origin: str,
        provider_id: str,
        operation: str,
        idempotency: str,
    ) -> dict[str, object]:
        existing = self.store.find_job_by_idempotency(owner_client, owner_origin, idempotency)
        if existing:
            if existing["request_hash"] != payload["requestHash"]:
                raise ConnectorError(
                    "JOB_IDEMPOTENCY_CONFLICT", "idempotencyKey 已绑定其他请求", 409
                )
            return self.projection(existing)

        relations = self._relations(payload.get("parent"), owner_client, owner_origin)
        inputs = safe_json(payload["inputs"], "inputs")
        options = safe_json(payload.get("options") or {}, "options")
        profile = None if payload.get("profile") is None else str(payload["profile"])
        adapter = self.capabilities.adapter(provider_id)
        provider_job = adapter.submit(
            operation=operation,
            inputs=dict(inputs),
            profile=profile,
            options=dict(options),
            context=ProviderContext(
                owner_client=owner_client,
                owner_origin=owner_origin,
                request_id=idempotency,
                artifacts=self.artifacts,
            ),
        )
        timestamp = iso(datetime.now(UTC))
        effective_options = dict(options)
        if profile is not None:
            effective_options = {"profile": profile, **effective_options}
        model_id = str(inputs.get("model") or "").strip()
        row = {
            "id": f"job_{uuid.uuid4().hex}",
            "owner_client": owner_client,
            "owner_origin": owner_origin,
            "provider": provider_id,
            "operation": operation,
            "request_hash": payload["requestHash"],
            "idempotency_key": idempotency,
            "contract_version": payload["contractVersion"],
            "capability_hash": payload["capabilityHash"],
            "capability_revision": payload["capabilityRevision"],
            "provider_job_id": provider_job.id,
            "provider_state": provider_job.state,
            "status": "accepted",
            "stage": "submitted",
            "attempt": 1,
            "relations": relations,
            "effective_options": effective_options,
            "model": {"id": model_id, "version": None, "revision": None} if model_id else None,
            "created_at": timestamp,
            "submitted_at": timestamp,
            "started_at": None,
            "updated_at": timestamp,
            "completed_at": None,
            "error": None,
            "result": None,
            "event_sequence": 1,
        }
        self.store.create_job(row)
        return self.projection(row)

    def get(self, job_id: str, session: dict[str, object]) -> dict[str, object]:
        row = self._job(job_id, session)
        if row["status"] not in _TERMINAL:
            row = self._refresh(row)
        return self.projection(row)

    def list(self, session: dict[str, object]) -> list[dict[str, object]]:
        rows = self.store.list_jobs(str(session["client_identity"]), str(session["origin"]))
        return [self.projection(row) for row in rows]

    def cancel(self, job_id: str, session: dict[str, object]) -> dict[str, object]:
        row = self._job(job_id, session)
        if row["status"] in _TERMINAL:
            return self.projection(row)
        adapter = self.capabilities.adapter(str(row["provider"]))
        try:
            provider_job = adapter.cancel(
                str(row["provider_job_id"]),
                state=row.get("provider_state"),
            )
        except ProviderError as exc:
            if exc.code == "PROVIDER_CONNECTION_REQUIRED":
                row = self._update_status(
                    row,
                    "connection_required",
                    error={"code": exc.code, "message": None, "recoverable": True},
                )
                return self.projection(row)
            raise
        row = self._reconcile(row, provider_job)
        if row["status"] not in _TERMINAL and row["status"] != "cancel_requested":
            row = self._update_status(row, "cancel_requested")
        return self.projection(row)

    def projection(self, row: dict[str, object]) -> dict[str, object]:
        return {
            "id": row["id"],
            "provider": row["provider"],
            "operation": row["operation"],
            "kind": "generation",
            "requestHash": row["request_hash"],
            "idempotencyKey": row["idempotency_key"],
            "contractVersion": row["contract_version"],
            "capabilityHash": row["capability_hash"],
            "capabilityRevision": row["capability_revision"],
            "status": row["status"],
            "stage": row.get("stage"),
            "attempt": row["attempt"],
            "relations": row.get("relations") or [],
            "effectiveOptions": row.get("effective_options") or {},
            "model": row.get("model"),
            "createdAt": row["created_at"],
            "submittedAt": row.get("submitted_at"),
            "startedAt": row.get("started_at"),
            "updatedAt": row["updated_at"],
            "completedAt": row.get("completed_at"),
            "error": row.get("error"),
            "result": row.get("result"),
            "eventSequence": row["event_sequence"],
        }

    def _refresh(self, row: dict[str, object]) -> dict[str, object]:
        adapter = self.capabilities.adapter(str(row["provider"]))
        try:
            provider_job = adapter.get(
                str(row["provider_job_id"]),
                state=row.get("provider_state"),
            )
        except ProviderError as exc:
            if exc.code == "PROVIDER_CONNECTION_REQUIRED":
                return self._update_status(
                    row,
                    "connection_required",
                    error={"code": exc.code, "message": None, "recoverable": True},
                )
            raise
        return self._reconcile(row, provider_job)

    def _reconcile(self, row: dict[str, object], provider_job: ProviderJob) -> dict[str, object]:
        status = provider_job.status
        if status not in {
            "running",
            "succeeded",
            "failed",
            "cancel_requested",
            "connection_required",
            "cancelled",
            "expired",
        }:
            raise ConnectorError("PROVIDER_JOB_INVALID", f"未知 Provider Job status: {status}", 502)
        error = None
        result = None
        if status == "succeeded":
            if provider_job.artifact is None:
                raise ConnectorError("PROVIDER_JOB_INVALID", "成功 Provider Job 缺少 Artifact", 502)
            artifact = self.artifacts.register(job=row, provider_artifact=provider_job.artifact)
            result = {"manifestId": None, "artifacts": [self.artifacts.summary(artifact)]}
        elif provider_job.error_code:
            error = {
                "code": provider_job.error_code,
                "message": None,
                "recoverable": bool(provider_job.retryable),
            }
        return self._update_status(row, status, result=result, error=error)

    def _update_status(
        self,
        row: dict[str, object],
        status: str,
        *,
        result: dict[str, object] | None = None,
        error: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if row["status"] == status and row.get("result") == result and row.get("error") == error:
            return row
        self._assert_transition(str(row["status"]), status)
        timestamp = iso(datetime.now(UTC))
        updated = dict(row)
        updated["status"] = status
        updated["stage"] = _stage(status)
        updated["updated_at"] = timestamp
        updated["event_sequence"] = int(row["event_sequence"]) + 1
        updated["error"] = error
        updated["result"] = result
        if status == "running" and not updated.get("started_at"):
            updated["started_at"] = timestamp
        if status in _TERMINAL:
            updated["completed_at"] = timestamp
        self.store.update_job(updated)
        return updated

    def _job(self, job_id: str, session: dict[str, object]) -> dict[str, object]:
        safe_id = _safe_id(job_id, "JOB_ID_INVALID")
        row = self.store.get_job(
            safe_id,
            str(session["client_identity"]),
            str(session["origin"]),
        )
        if not row:
            raise ConnectorError("JOB_NOT_FOUND", "Job 不存在", 404)
        return row

    def _session_snapshot(self, session: dict[str, object]) -> dict[str, object]:
        snapshot = self.capabilities.get(str(session["capability_hash"]))
        if not snapshot:
            raise ConnectorError(
                "CONNECTOR_CAPABILITY_STALE", "Session capability snapshot 不存在", 409
            )
        if snapshot.get("revision") != session["capability_revision"]:
            raise ConnectorError(
                "CONNECTOR_CAPABILITY_STALE", "Session capability revision 不匹配", 409
            )
        return snapshot

    def _validate_submit_contract(
        self,
        payload: dict[str, Any],
        provider: dict[str, object],
        capability: dict[str, object],
        session: dict[str, object],
    ) -> None:
        inputs = payload.get("inputs")
        options = payload.get("options") if payload.get("options") is not None else {}
        output_roles = payload.get("outputRoles")
        profile = payload.get("profile")
        if not isinstance(inputs, dict):
            raise ConnectorError("JOB_REQUEST_INVALID", "Job inputs 必须是对象", 422)
        if not isinstance(options, dict):
            raise ConnectorError("JOB_REQUEST_INVALID", "Job options 必须是对象", 422)
        if not isinstance(output_roles, list) or not all(
            isinstance(role, str) and role.strip() for role in output_roles
        ):
            raise ConnectorError("JOB_OUTPUT_ROLE_INVALID", "Job outputRoles 必须是字符串数组", 422)
        if profile is not None and (not isinstance(profile, str) or not profile.strip()):
            raise ConnectorError("JOB_PROFILE_INVALID", "Job profile 必须是非空字符串或 null", 422)
        for field in ("metadata", "retention", "parent"):
            value = payload.get(field)
            if value is not None and not isinstance(value, dict):
                raise ConnectorError("JOB_REQUEST_INVALID", f"Job {field} 必须是对象或 null", 422)

        if payload.get("capabilityHash") != session["capability_hash"]:
            raise ConnectorError(
                "JOB_CAPABILITY_STALE", "Job capabilityHash 与 session 不匹配", 409
            )
        if payload.get("capabilityRevision") != session["capability_revision"]:
            raise ConnectorError(
                "JOB_CAPABILITY_STALE", "Job capabilityRevision 与 session 不匹配", 409
            )
        if str(payload.get("contractVersion") or "") != str(provider.get("contractVersion") or "1"):
            raise ConnectorError("JOB_CONTRACT_MISMATCH", "Job contractVersion 不匹配", 409)
        if str(payload.get("operationVersion") or "") != str(capability.get("version") or ""):
            raise ConnectorError(
                "JOB_OPERATION_VERSION_MISMATCH", "Job operationVersion 不匹配", 409
            )
        requested_roles = list(dict.fromkeys(role.strip() for role in output_roles))
        output = capability.get("output") if isinstance(capability.get("output"), dict) else {}
        allowed = set(output.get("roles") or [])
        required = set(output.get("required") or [])
        if any(role not in allowed for role in requested_roles) or not required.issubset(
            requested_roles
        ):
            raise ConnectorError(
                "JOB_OUTPUT_ROLE_INVALID", "Job outputRoles 不符合 capability", 422
            )
        profiles = capability.get("profiles")
        if profile is not None and isinstance(profiles, dict) and str(profile) not in profiles:
            raise ConnectorError("JOB_PROFILE_INVALID", "Job profile 不符合 capability", 422)
        safe_json(inputs, "inputs")
        safe_json(options, "options")
        safe_json(payload.get("metadata"), "metadata")
        safe_json(payload.get("retention"), "retention")
        safe_json(payload.get("parent"), "parent")

    def _relations(
        self,
        parent: object,
        owner_client: str,
        owner_origin: str,
    ) -> list[dict[str, str]]:
        if parent is None:
            return []
        if not isinstance(parent, dict):
            raise ConnectorError("JOB_PARENT_INVALID", "Job parent 必须是对象", 422)
        job_id = _safe_id(str(parent.get("jobId") or ""), "JOB_PARENT_INVALID")
        if not self.store.get_job(job_id, owner_client, owner_origin):
            raise ConnectorError("JOB_PARENT_INVALID", "Parent Job 不存在", 422)
        return [{"type": "parent", "jobId": job_id}]

    @staticmethod
    def _assert_transition(previous: str, current: str) -> None:
        if previous == current:
            return
        if previous in _TERMINAL or current not in _ALLOWED_TRANSITIONS.get(previous, set()):
            raise ConnectorError(
                "JOB_STATUS_REGRESSION", f"非法 Job 状态迁移: {previous} -> {current}", 409
            )


def _safe_id(value: str, code: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 160 or any(char not in _SAFE_ID_CHARS for char in text):
        raise ConnectorError(code, "ID 不是安全 opaque identifier", 422)
    return text


def _stage(status: str) -> str:
    return {
        "accepted": "submitted",
        "queued": "queued",
        "running": "generation",
        "connection_required": "connection",
        "cancel_requested": "cancelling",
        "succeeded": "artifact",
        "failed": "failed",
        "cancelled": "cancelled",
        "expired": "expired",
    }[status]
