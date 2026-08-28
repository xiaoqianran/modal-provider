from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import modal
from modal.exception import (
    AuthError,
    InternalError,
    NotFoundError,
    OutputExpiredError,
    PermissionDeniedError,
    RemoteError,
    ServiceError,
)
from modal.exception import ConnectionError as ModalConnectionError
from modal.exception import TimeoutError as ModalTimeoutError

from . import artifacts, capabilities
from .constants import APP_NAME, SUBMIT_FUNCTION
from .contracts import ContractError, normalize_request, validate_artifact
from .modal_session import NotConnectedError, client
from .storage import data_dir

_DB_VERSION = 2
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
TERMINAL = {"succeeded", "failed", "cancelled", "expired"}
_RECOVERABLE = (
    NotConnectedError,
    AuthError,
    PermissionDeniedError,
    ModalConnectionError,
    InternalError,
    ServiceError,
    ModalTimeoutError,
    TimeoutError,
)


def default_db_path() -> Path:
    return data_dir() / "jobs.sqlite3"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    model: str
    remote_call_id: str | None
    status: str
    created_at: str
    updated_at: str
    result: dict[str, object] | None = None
    error_code: str | None = None
    retryable: bool | None = None

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "model": self.model,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error_code": self.error_code,
            "retryable": self.retryable,
        }


class JobStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._init_db()
        self._load()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _init_db(self) -> None:
        with self._connect() as db:
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if version > _DB_VERSION:
                raise RuntimeError(f"Job DB version is newer than supported: {version}")

            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
            ).fetchone()
            if exists:
                columns = db.execute("PRAGMA table_info(jobs)").fetchall()
                required = {
                    "id", "model", "remote_call_id", "status", "created_at", "updated_at",
                    "result_json", "error_code", "retryable",
                }
                present = {row[1] for row in columns}
                missing = required - present
                if missing:
                    raise RuntimeError(
                        f"Job DB schema is incompatible: missing {sorted(missing)}"
                    )
                remote = next(row for row in columns if row[1] == "remote_call_id")
                if remote[3]:
                    db.execute(
                        """
                        CREATE TABLE jobs_v2 (
                            id TEXT PRIMARY KEY, model TEXT NOT NULL, remote_call_id TEXT,
                            status TEXT NOT NULL, created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            result_json TEXT, error_code TEXT, retryable INTEGER
                        )
                        """
                    )
                    db.execute(
                        """
                        INSERT INTO jobs_v2
                        SELECT id, model, remote_call_id, status, created_at, updated_at,
                               result_json, error_code, retryable
                        FROM jobs
                        """
                    )
                    db.execute("DROP TABLE jobs")
                    db.execute("ALTER TABLE jobs_v2 RENAME TO jobs")
            else:
                db.execute(
                    """
                    CREATE TABLE jobs (
                        id TEXT PRIMARY KEY, model TEXT NOT NULL, remote_call_id TEXT,
                        status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        result_json TEXT, error_code TEXT, retryable INTEGER
                    )
                    """
                )
            db.execute(f"PRAGMA user_version = {_DB_VERSION}")

    def _load(self) -> None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, model, remote_call_id, status, created_at, updated_at, "
                "result_json, error_code, retryable FROM jobs"
            ).fetchall()
        with self._lock:
            self._jobs = {
                row[0]: Job(
                    id=row[0],
                    model=row[1],
                    remote_call_id=row[2],
                    status=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                    result=json.loads(row[6]) if row[6] else None,
                    error_code=row[7],
                    retryable=None if row[8] is None else bool(row[8]),
                )
                for row in rows
            }

    def save(self, job: Job) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    model=excluded.model, remote_call_id=excluded.remote_call_id,
                    status=excluded.status, updated_at=excluded.updated_at,
                    result_json=excluded.result_json, error_code=excluded.error_code,
                    retryable=excluded.retryable
                """,
                (
                    job.id,
                    job.model,
                    job.remote_call_id,
                    job.status,
                    job.created_at,
                    job.updated_at,
                    json.dumps(job.result, separators=(",", ":")) if job.result else None,
                    job.error_code,
                    None if job.retryable is None else int(job.retryable),
                ),
            )
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def list(self, limit: int = 50) -> list[dict[str, object]]:
        with self._lock:
            rows = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [job.public() for job in rows[:limit]]


class JobService:
    def __init__(self, store: JobStore | None = None) -> None:
        self.store = store or JobStore()

    def submit(
        self,
        payload: dict[str, object],
        *,
        job_id: str | None = None,
    ) -> dict[str, object]:
        request = normalize_request(payload)
        capabilities.ensure_model(str(request["model"]))
        local_job_id = job_id or f"job_{uuid.uuid4().hex}"
        if not _JOB_ID.fullmatch(local_job_id):
            raise ContractError("job_id must be a URL-safe identifier")
        try:
            self.store.get(local_job_id)
        except KeyError:
            pass
        else:
            raise ContractError("job_id already exists")

        # 先完成本地/认证 preflight，再持久化 intent，最后触发远端调用。
        fn = modal.Function.from_name(APP_NAME, SUBMIT_FUNCTION, client=client())
        timestamp = _now()
        intent = Job(
            id=local_job_id,
            model=str(request["model"]),
            remote_call_id=None,
            status="submitting",
            created_at=timestamp,
            updated_at=timestamp,
            retryable=False,
        )
        self.store.save(intent)
        try:
            call = fn.spawn(request)
        except Exception:
            latest = self.store.get(local_job_id)
            return self._set(
                latest,
                "connection_required",
                error_code="remote.submission_unknown",
                retryable=False,
            )

        latest = self.store.get(local_job_id)
        if latest.status == "cancel_requested":
            try:
                modal.FunctionCall.from_id(call.object_id, client=client()).cancel()
            except _RECOVERABLE:
                cancelled = replace(
                    latest,
                    remote_call_id=call.object_id,
                    updated_at=_now(),
                    error_code="modal.connection_required",
                    retryable=True,
                )
                self.store.save(cancelled)
                return cancelled.public()
            except (OutputExpiredError, NotFoundError):
                expired = replace(
                    latest,
                    remote_call_id=call.object_id,
                    status="expired",
                    updated_at=_now(),
                    error_code="remote.output_expired",
                    retryable=False,
                )
                self.store.save(expired)
                return expired.public()
            cancelled = replace(
                latest,
                remote_call_id=call.object_id,
                updated_at=_now(),
                error_code=None,
                retryable=True,
            )
            self.store.save(cancelled)
            return cancelled.public()

        running = replace(
            latest,
            remote_call_id=call.object_id,
            status="running",
            updated_at=_now(),
            retryable=True,
        )
        self.store.save(running)
        return running.public()

    def poll(self, job_id: str) -> dict[str, object]:
        job = self.store.get(job_id)
        if job.status in TERMINAL:
            return job.public()
        if not job.remote_call_id:
            if job.status == "cancel_requested":
                return job.public()
            if job.status == "submitting":
                return self._set(
                    job,
                    "connection_required",
                    error_code="remote.submission_unknown",
                    retryable=False,
                )
            return job.public()
        try:
            call = modal.FunctionCall.from_id(job.remote_call_id, client=client())
            value = call.get(timeout=0)
        except (ModalTimeoutError, TimeoutError):
            if job.status == "connection_required":
                return self._set(job, "running", retryable=True)
            return job.public()
        except (OutputExpiredError, NotFoundError):
            return self._set(job, "expired", error_code="remote.output_expired", retryable=False)
        except _RECOVERABLE:
            return self._set(
                job, "connection_required", error_code="modal.connection_required", retryable=True
            )
        except RemoteError:
            if job.status == "cancel_requested":
                return self._set(
                    job, "cancelled", error_code="remote.cancelled", retryable=False
                )
            return self._set(job, "failed", error_code="remote.execution_failed", retryable=False)
        except Exception:
            return self._set(job, "failed", error_code="remote.execution_failed", retryable=False)

        if not isinstance(value, dict) or value.get("model") != job.model:
            return self._set(job, "failed", error_code="remote.invalid_response", retryable=False)
        try:
            artifact = validate_artifact(value.get("artifact"))
        except ContractError:
            return self._set(
                job, "failed", error_code="artifact.invalid_descriptor", retryable=False
            )
        return self._set(job, "succeeded", result={"artifact": artifact}, retryable=False)

    def cancel(self, job_id: str) -> dict[str, object]:
        job = self.store.get(job_id)
        if job.status in TERMINAL:
            return job.public()
        if not job.remote_call_id:
            return self._set(
                job,
                "cancel_requested",
                error_code=None,
                retryable=True,
            )
        try:
            modal.FunctionCall.from_id(job.remote_call_id, client=client()).cancel()
        except _RECOVERABLE:
            return self._set(
                job, "connection_required", error_code="modal.connection_required", retryable=True
            )
        except (OutputExpiredError, NotFoundError):
            return self._set(job, "expired", error_code="remote.output_expired", retryable=False)
        return self._set(job, "cancel_requested", retryable=True)

    def artifact(self, job_id: str) -> tuple[dict[str, object], Path]:
        state = self.poll(job_id)
        if state["status"] != "succeeded" or not isinstance(state.get("result"), dict):
            raise RuntimeError("job artifact is not ready")
        descriptor = state["result"]["artifact"]
        return descriptor, artifacts.fetch(descriptor)

    def _set(
        self,
        job: Job,
        status: str,
        *,
        result: dict[str, object] | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> dict[str, object]:
        if job.status in TERMINAL:
            return job.public()
        updated = replace(
            job,
            status=status,
            updated_at=_now(),
            result=result,
            error_code=error_code,
            retryable=retryable,
        )
        self.store.save(updated)
        return updated.public()
