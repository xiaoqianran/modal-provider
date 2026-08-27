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

from . import artifacts, generation, models
from .contracts import ContractError
from .modal_session import NotConnectedError, client
from .storage import data_dir

_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "expired"})
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_RECOVERABLE = (
    NotConnectedError,
    AuthError,
    PermissionDeniedError,
    ModalConnectionError,
    ModalTimeoutError,
    InternalError,
    ServiceError,
    TimeoutError,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def default_db_path() -> Path:
    return data_dir() / "jobs.sqlite3"


@dataclass
class Job:
    id: str
    model: str
    profile: str
    seed: int
    input_path: str
    input_sha256: str
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
            "profile": self.profile,
            "seed": self.seed,
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
        self._initialize()
        self._load()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    input_path TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    remote_call_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result_json TEXT,
                    error_code TEXT,
                    retryable INTEGER
                )
                """
            )

    def _load(self) -> None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,model,profile,seed,input_path,input_sha256,remote_call_id,status,"
                "created_at,updated_at,result_json,error_code,retryable FROM jobs"
            ).fetchall()
        with self._lock:
            self._jobs = {
                row[0]: Job(
                    id=row[0],
                    model=row[1],
                    profile=row[2],
                    seed=row[3],
                    input_path=row[4],
                    input_sha256=row[5],
                    remote_call_id=row[6],
                    status=row[7],
                    created_at=row[8],
                    updated_at=row[9],
                    result=json.loads(row[10]) if row[10] else None,
                    error_code=row[11],
                    retryable=None if row[12] is None else bool(row[12]),
                )
                for row in rows
            }

    def save(self, job: Job) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    model=excluded.model,
                    profile=excluded.profile,
                    seed=excluded.seed,
                    input_path=excluded.input_path,
                    input_sha256=excluded.input_sha256,
                    remote_call_id=excluded.remote_call_id,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    result_json=excluded.result_json,
                    error_code=excluded.error_code,
                    retryable=excluded.retryable
                """,
                (
                    job.id,
                    job.model,
                    job.profile,
                    job.seed,
                    job.input_path,
                    job.input_sha256,
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
        canonical: bytes,
        *,
        model: str,
        profile: str = "recommended",
        seed: int = 42,
        job_id: str | None = None,
    ) -> dict[str, object]:
        local_id = job_id or f"job_{uuid.uuid4().hex}"
        if not _JOB_ID.fullmatch(local_id):
            raise ContractError("job_id must be a URL-safe identifier")
        models.options_for(model, profile, seed)
        local_input = artifacts.validate_canonical_png(canonical)
        try:
            existing = self.store.get(local_id)
        except KeyError:
            existing = None
        if existing is not None:
            expected = (model, profile, seed, str(local_input["sha256"]))
            actual = (existing.model, existing.profile, existing.seed, existing.input_sha256)
            if actual != expected:
                raise ContractError("job_id is already bound to another request")
            return existing.public()

        uploaded = artifacts.upload_canonical(canonical)
        timestamp = _now()
        intent = Job(
            id=local_id,
            model=model,
            profile=profile,
            seed=seed,
            input_path=str(uploaded["path"]),
            input_sha256=str(uploaded["sha256"]),
            remote_call_id=None,
            status="submitting",
            created_at=timestamp,
            updated_at=timestamp,
            retryable=True,
        )
        self.store.save(intent)
        return self._bind(intent).public()

    def _bind(self, job: Job) -> Job:
        try:
            remote = generation.submit(job.model, job.input_path, job.profile, job.seed)
        except _RECOVERABLE:
            return self._save(
                job,
                status="connection_required",
                error_code="remote.submission_unknown",
                retryable=True,
            )
        remote_id = str(remote["call_id"])
        return self._save(
            job,
            remote_call_id=remote_id,
            status="running",
            error_code=None,
            retryable=True,
        )

    def poll(self, job_id: str) -> dict[str, object]:
        job = self.store.get(job_id)
        if job.status in _TERMINAL:
            return job.public()
        if not job.remote_call_id:
            job = self._bind(job)
            if not job.remote_call_id:
                return job.public()
        try:
            call = modal.FunctionCall.from_id(job.remote_call_id, client=client())
            value = call.get(timeout=0)
        except (ModalTimeoutError, TimeoutError):
            if job.status != "running":
                job = self._save(job, status="running", error_code=None, retryable=True)
            return job.public()
        except (OutputExpiredError, NotFoundError):
            return self._save(
                job, status="expired", error_code="remote.output_expired", retryable=False
            ).public()
        except _RECOVERABLE:
            return self._save(
                job,
                status="connection_required",
                error_code="modal.connection_required",
                retryable=True,
            ).public()
        except RemoteError:
            status = "cancelled" if job.status == "cancel_requested" else "failed"
            return self._save(
                job, status=status, error_code="remote.execution_failed", retryable=False
            ).public()
        if not isinstance(value, dict) or value.get("model") != job.model:
            return self._save(
                job, status="failed", error_code="remote.invalid_response", retryable=False
            ).public()
        try:
            descriptor, _path = artifacts.fetch(value.get("artifact"), model=job.model)
        except ContractError:
            return self._save(
                job, status="failed", error_code="artifact.invalid", retryable=False
            ).public()
        return self._save(
            job,
            status="succeeded",
            result={"artifact": descriptor},
            error_code=None,
            retryable=False,
        ).public()

    def cancel(self, job_id: str) -> dict[str, object]:
        job = self.store.get(job_id)
        if job.status in _TERMINAL:
            return job.public()
        if not job.remote_call_id:
            return self._save(
                job,
                status="connection_required",
                error_code="remote.submission_unknown",
                retryable=True,
            ).public()
        try:
            modal.FunctionCall.from_id(job.remote_call_id, client=client()).cancel()
        except _RECOVERABLE:
            return self._save(
                job,
                status="connection_required",
                error_code="modal.connection_required",
                retryable=True,
            ).public()
        except (OutputExpiredError, NotFoundError):
            return self._save(
                job, status="expired", error_code="remote.output_expired", retryable=False
            ).public()
        return self._save(job, status="cancel_requested", retryable=True).public()

    def artifact(self, job_id: str) -> tuple[dict[str, object], Path]:
        state = self.poll(job_id)
        if state["status"] != "succeeded" or not isinstance(state.get("result"), dict):
            raise RuntimeError("job artifact is not ready")
        descriptor = state["result"]["artifact"]
        return artifacts.cached(descriptor, model=str(state["model"]))

    def _save(self, job: Job, **changes: object) -> Job:
        if job.status in _TERMINAL:
            return job
        updated = replace(job, updated_at=_now(), **changes)
        self.store.save(updated)
        return updated
