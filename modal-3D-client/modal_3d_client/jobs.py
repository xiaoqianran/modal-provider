from __future__ import annotations

import json
import logging
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

from . import artifacts, background, generation, models
from .constants import CLIENT_INPUT_PREFIX
from .contracts import ContractError
from .modal_session import NotConnectedError, client
from .storage import data_dir

_LOG = logging.getLogger(__name__)

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

_JOB_COLUMNS = (
    "id",
    "model",
    "profile",
    "seed",
    "input_path",
    "input_sha256",
    "prepare_call_id",
    "remote_call_id",
    "status",
    "created_at",
    "updated_at",
    "result_json",
    "error_code",
    "retryable",
    "conditioning_json",
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
    prepare_call_id: str | None = None
    result: dict[str, object] | None = None
    error_code: str | None = None
    retryable: bool | None = None
    conditioning: dict[str, object] | None = None

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
            "conditioning": self.conditioning,
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
            self._create_table(db, "jobs", if_not_exists=True)
            schema = {row[1]: row for row in db.execute("PRAGMA table_info(jobs)")}
            if not set(_JOB_COLUMNS) <= schema.keys() or schema["remote_call_id"][3]:
                self._rebuild_legacy_table(db, schema)

    @staticmethod
    def _create_table(db: sqlite3.Connection, name: str, *, if_not_exists: bool = False) -> None:
        guard = "IF NOT EXISTS " if if_not_exists else ""
        db.execute(
            f"""
            CREATE TABLE {guard}{name} (
                id TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                profile TEXT NOT NULL,
                seed INTEGER NOT NULL,
                input_path TEXT NOT NULL,
                input_sha256 TEXT NOT NULL,
                prepare_call_id TEXT,
                remote_call_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                result_json TEXT,
                error_code TEXT,
                retryable INTEGER,
                conditioning_json TEXT
            )
            """
        )

    def _rebuild_legacy_table(self, db: sqlite3.Connection, schema: dict[str, tuple]) -> None:
        """Atomically normalize every historical jobs schema to the current one."""

        columns = set(schema)

        def source(column: str, fallback: str) -> str:
            return f'COALESCE("{column}", {fallback})' if column in columns else fallback

        error_code = source("error_code", "NULL")
        if "error" in columns:
            error_code = f'COALESCE({error_code}, "error")'

        # A process may have been killed during an earlier migration attempt.
        # The canonical jobs table remains intact until the final rename, so a
        # stale temporary table is always safe to discard and rebuild.
        db.execute("DROP TABLE IF EXISTS jobs_migrated")
        self._create_table(db, "jobs_migrated")
        db.execute(
            f"""
            INSERT INTO jobs_migrated ({", ".join(_JOB_COLUMNS)})
            SELECT
                "id",
                "model",
                {source("profile", "'recommended'")},
                {source("seed", "42")},
                {source("input_path", "''")},
                {source("input_sha256", "''")},
                {source("prepare_call_id", "NULL")},
                {source("remote_call_id", "NULL")},
                {source("status", "'failed'")},
                {source("created_at", "''")},
                {source("updated_at", source("created_at", "''"))},
                {source("result_json", "NULL")},
                {error_code},
                {source("retryable", "NULL")},
                {source("conditioning_json", "NULL")}
            FROM jobs
            """
        )
        db.execute("DROP TABLE jobs")
        db.execute("ALTER TABLE jobs_migrated RENAME TO jobs")

    def _load(self) -> None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,model,profile,seed,input_path,input_sha256,prepare_call_id,remote_call_id,status,"
                "created_at,updated_at,result_json,error_code,retryable,conditioning_json FROM jobs"
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
                    prepare_call_id=row[6],
                    remote_call_id=row[7],
                    status=row[8],
                    created_at=row[9],
                    updated_at=row[10],
                    result=json.loads(row[11]) if row[11] else None,
                    error_code=row[12],
                    retryable=None if row[13] is None else bool(row[13]),
                    conditioning=json.loads(row[14]) if row[14] else None,
                )
                for row in rows
            }

    def save(self, job: Job) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO jobs (
                    id, model, profile, seed, input_path, input_sha256,
                    prepare_call_id, remote_call_id, status, created_at, updated_at,
                    result_json, error_code, retryable, conditioning_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    model=excluded.model,
                    profile=excluded.profile,
                    seed=excluded.seed,
                    input_path=excluded.input_path,
                    input_sha256=excluded.input_sha256,
                    prepare_call_id=excluded.prepare_call_id,
                    remote_call_id=excluded.remote_call_id,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    result_json=excluded.result_json,
                    error_code=excluded.error_code,
                    retryable=excluded.retryable,
                    conditioning_json=excluded.conditioning_json
                """,
                (
                    job.id,
                    job.model,
                    job.profile,
                    job.seed,
                    job.input_path,
                    job.input_sha256,
                    job.prepare_call_id,
                    job.remote_call_id,
                    job.status,
                    job.created_at,
                    job.updated_at,
                    json.dumps(job.result, separators=(",", ":")) if job.result else None,
                    job.error_code,
                    None if job.retryable is None else int(job.retryable),
                    json.dumps(job.conditioning, separators=(",", ":"))
                    if job.conditioning
                    else None,
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

    def pending_continuations(self) -> list[Job]:
        """Return jobs whose next remote stage still depends on local orchestration."""
        with self._lock:
            return [
                job
                for job in self._jobs.values()
                if job.status not in _TERMINAL
                and job.remote_call_id is None
                and (job.status != "cancel_requested" or job.prepare_call_id is not None)
            ]


class JobService:
    def __init__(
        self,
        store: JobStore | None = None,
        *,
        auto_reconcile: bool = False,
        reconcile_interval_s: float = 0.5,
    ) -> None:
        self.store = store or JobStore()
        self._submit_locks_guard = threading.Lock()
        self._submit_locks: dict[str, tuple[threading.Lock, int]] = {}
        self._reconcile_interval_s = max(0.05, float(reconcile_interval_s))
        self._reconcile_stop = threading.Event()
        self._reconcile_wakeup = threading.Event()
        self._reconcile_guard = threading.Lock()
        self._reconcile_thread: threading.Thread | None = None
        if auto_reconcile:
            self.start_reconciler()

    def start_reconciler(self) -> None:
        """Advance durable prepare -> generation transitions independently of HTTP polling."""
        with self._reconcile_guard:
            if self._reconcile_thread is not None and self._reconcile_thread.is_alive():
                self._reconcile_wakeup.set()
                return
            self._reconcile_stop.clear()
            self._reconcile_wakeup.set()
            thread = threading.Thread(
                target=self._reconcile_loop,
                name="modal-3d-job-reconciler",
                daemon=True,
            )
            self._reconcile_thread = thread
            thread.start()

    def stop_reconciler(self, timeout: float = 2.0) -> None:
        with self._reconcile_guard:
            thread = self._reconcile_thread
            if thread is None:
                return
            self._reconcile_stop.set()
            self._reconcile_wakeup.set()
        if thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        with self._reconcile_guard:
            if self._reconcile_thread is thread and not thread.is_alive():
                self._reconcile_thread = None

    def close(self) -> None:
        self.stop_reconciler()

    def reconcile_once(self) -> int:
        """Advance every job that still needs a locally-triggered remote stage."""
        advanced = 0
        for job in self.store.pending_continuations():
            before = (job.prepare_call_id, job.remote_call_id, job.status, job.updated_at)
            try:
                state = self.poll(job.id)
            except (KeyError, ContractError):
                continue
            except Exception:  # noqa: BLE001 - keep one bad job from killing the daemon
                _LOG.exception("3D job reconciler failed for %s", job.id)
                continue
            latest = self.store.get(job.id)
            after = (
                latest.prepare_call_id,
                latest.remote_call_id,
                latest.status,
                latest.updated_at,
            )
            if after != before or state.get("status") in _TERMINAL:
                advanced += 1
        return advanced

    def _reconcile_loop(self) -> None:
        while not self._reconcile_stop.is_set():
            self._reconcile_wakeup.clear()
            self.reconcile_once()
            self._reconcile_wakeup.wait(self._reconcile_interval_s)

    def _wake_reconciler(self) -> None:
        self._reconcile_wakeup.set()

    @contextmanager
    def _submission_lock(self, job_id: str) -> Iterator[None]:
        """Serialize only duplicate submissions for the same request id.

        Different jobs still condition/warm in parallel. Reference counting lets
        lock entries disappear once the last waiter leaves.
        """
        with self._submit_locks_guard:
            entry = self._submit_locks.get(job_id)
            if entry is None:
                lock = threading.RLock()
                refs = 0
            else:
                lock, refs = entry
            self._submit_locks[job_id] = (lock, refs + 1)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._submit_locks_guard:
                current_lock, refs = self._submit_locks[job_id]
                if current_lock is not lock:
                    raise RuntimeError("submission lock identity changed unexpectedly")
                if refs == 1:
                    del self._submit_locks[job_id]
                else:
                    self._submit_locks[job_id] = (lock, refs - 1)

    def submit(
        self,
        source_image: bytes,
        *,
        model: str,
        profile: str = "recommended",
        seed: int = 42,
        job_id: str | None = None,
        mask: bytes | None = None,
    ) -> dict[str, object]:
        local_id = job_id or f"job_{uuid.uuid4().hex}"
        if not _JOB_ID.fullmatch(local_id):
            raise ContractError("job_id must be a URL-safe identifier")
        with self._submission_lock(local_id):
            return self._submit_locked(
                source_image,
                model=model,
                profile=profile,
                seed=seed,
                job_id=local_id,
                mask=mask,
            )

    def submit_remote_source(
        self,
        source_path: str,
        *,
        source_sha256: str,
        model: str,
        profile: str = "recommended",
        seed: int = 42,
        job_id: str | None = None,
    ) -> dict[str, object]:
        """Start cloud-side conditioning without blocking the submit request.

        The raw source already lives in the shared Modal Volume. We persist the
        preparation FunctionCall separately from the generation FunctionCall so
        polling, cancellation and Connector restarts can advance the same job.
        """
        local_id = job_id or f"job_{uuid.uuid4().hex}"
        if not _JOB_ID.fullmatch(local_id):
            raise ContractError("job_id must be a URL-safe identifier")
        with self._submission_lock(local_id):
            models.options_for(model, profile, seed)
            existing = self._existing(local_id, model, profile, seed, source_sha256)
            if existing is not None:
                return existing.public()
            timestamp = _now()
            intent = Job(
                id=local_id,
                model=model,
                profile=profile,
                seed=seed,
                input_path=source_path,
                input_sha256=source_sha256,
                remote_call_id=None,
                status="running",
                created_at=timestamp,
                updated_at=timestamp,
                retryable=True,
            )
            self.store.save(intent)
            started = self._start_preparation(intent)
            self._wake_reconciler()
            return started.public()

    def _start_preparation(self, job: Job) -> Job:
        if job.status == "cancel_requested":
            return job
        try:
            generation.prefetch(job.model)
        except _RECOVERABLE:
            pass
        try:
            call = background.spawn_prepare_source(job.input_path)
        except _RECOVERABLE:
            latest = self.store.get(job.id)
            if latest.status == "cancel_requested":
                return latest
            return self._save(
                latest,
                status="connection_required",
                error_code="modal.connection_required",
                retryable=True,
            )
        latest = self.store.get(job.id)
        if latest.status == "cancel_requested":
            try:
                call.cancel()
            except _RECOVERABLE:
                pass
            return latest
        return self._save(
            latest,
            prepare_call_id=str(call.object_id),
            status="running",
            error_code=None,
            retryable=True,
        )

    def _poll_preparation(self, job: Job) -> Job:
        if not job.prepare_call_id:
            return job
        try:
            call = modal.FunctionCall.from_id(job.prepare_call_id, client=client())
            prepared = call.get(timeout=0)
        except (ModalTimeoutError, TimeoutError):
            if job.status not in {"running", "cancel_requested"}:
                return self._save(job, status="running", error_code=None, retryable=True)
            return job
        except (OutputExpiredError, NotFoundError):
            return self._save(
                job,
                prepare_call_id=None,
                status="connection_required",
                error_code="remote.preparation_expired",
                retryable=True,
            )
        except _RECOVERABLE:
            return self._save(
                job,
                status="connection_required",
                error_code="modal.connection_required",
                retryable=True,
            )
        except RemoteError:
            if job.status == "cancel_requested":
                return self._save(
                    job,
                    prepare_call_id=None,
                    status="cancelled",
                    error_code="remote.cancelled",
                    retryable=False,
                )
            return self._save(
                job,
                prepare_call_id=None,
                status="failed",
                error_code="remote.conditioning_failed",
                retryable=False,
            )
        if not isinstance(prepared, dict):
            return self._save(
                job,
                prepare_call_id=None,
                status="failed",
                error_code="conditioning.invalid_response",
                retryable=False,
            )
        if str(prepared.get("source_sha256") or "") != job.input_sha256:
            return self._save(
                job,
                prepare_call_id=None,
                status="failed",
                error_code="conditioning.identity_changed",
                retryable=False,
            )
        input_path = str(prepared.get("path") or "")
        if not input_path.startswith(CLIENT_INPUT_PREFIX):
            return self._save(
                job,
                prepare_call_id=None,
                status="failed",
                error_code="conditioning.invalid_path",
                retryable=False,
            )
        latest = self.store.get(job.id)
        if latest.status == "cancel_requested":
            return self._save(
                latest,
                prepare_call_id=None,
                status="cancelled",
                error_code="remote.cancelled",
                retryable=False,
            )
        prepared_job = self._save(
            latest,
            prepare_call_id=None,
            input_path=input_path,
            conditioning=dict(prepared.get("conditioning") or {}),
            status="running",
            error_code=None,
            retryable=True,
        )
        return self._bind(prepared_job)

    def _existing(
        self, local_id: str, model: str, profile: str, seed: int, input_sha256: str
    ) -> Job | None:
        try:
            existing = self.store.get(local_id)
        except KeyError:
            return None
        expected = (model, profile, seed, input_sha256)
        actual = (existing.model, existing.profile, existing.seed, existing.input_sha256)
        if actual != expected:
            raise ContractError("job_id is already bound to another request")
        return existing

    def _create_and_bind(
        self,
        *,
        local_id: str,
        model: str,
        profile: str,
        seed: int,
        input_path: str,
        input_sha256: str,
        conditioning: dict[str, object],
    ) -> Job:
        timestamp = _now()
        intent = Job(
            id=local_id,
            model=model,
            profile=profile,
            seed=seed,
            input_path=input_path,
            input_sha256=input_sha256,
            prepare_call_id=None,
            remote_call_id=None,
            status="submitting",
            created_at=timestamp,
            updated_at=timestamp,
            retryable=True,
            conditioning=conditioning,
        )
        self.store.save(intent)
        return self._bind(intent)

    def _submit_locked(
        self,
        source_image: bytes,
        *,
        model: str,
        profile: str = "recommended",
        seed: int = 42,
        job_id: str | None = None,
        mask: bytes | None = None,
    ) -> dict[str, object]:
        local_id = job_id or f"job_{uuid.uuid4().hex}"
        if not _JOB_ID.fullmatch(local_id):
            raise ContractError("job_id must be a URL-safe identifier")
        models.options_for(model, profile, seed)
        local_input = artifacts.validate_source_image(source_image)
        existing = self._existing(local_id, model, profile, seed, str(local_input["sha256"]))
        if existing is not None:
            return existing.public()

        # The model is already known at this point. Start its GPU container now so
        # model loading overlaps T4 background removal/local canonicalization.
        # Prefetch is only a latency optimization; the real generation submission
        # below remains authoritative if this best-effort spawn cannot be sent.
        try:
            generation.prefetch(model)
        except _RECOVERABLE:
            pass

        uploaded = artifacts.upload_source(source_image, mask=mask)
        input_path = str(uploaded["path"])
        if not input_path.startswith(CLIENT_INPUT_PREFIX):
            raise ContractError(f"uploaded input must live under {CLIENT_INPUT_PREFIX}")
        return self._create_and_bind(
            local_id=local_id,
            model=model,
            profile=profile,
            seed=seed,
            input_path=input_path,
            input_sha256=str(uploaded["sha256"]),
            conditioning=dict(uploaded["conditioning"]),  # type: ignore[arg-type]
        ).public()

    def _bind(self, job: Job) -> Job:
        if job.status == "cancel_requested":
            return job
        try:
            call = generation.submit(job.model, job.input_path, job.profile, job.seed)
        except _RECOVERABLE:
            latest = self.store.get(job.id)
            if latest.status == "cancel_requested":
                return latest
            return self._save(
                latest,
                status="connection_required",
                error_code="remote.submission_unknown",
                retryable=True,
            )
        remote_id = str(call.object_id)
        latest = self.store.get(job.id)
        if latest.status in {"cancel_requested", "cancelled"}:
            try:
                modal.FunctionCall.from_id(remote_id, client=client()).cancel()
            except _RECOVERABLE:
                if latest.status == "cancelled":
                    return latest
                return self._save(
                    latest,
                    remote_call_id=remote_id,
                    status="cancel_requested",
                    error_code="modal.connection_required",
                    retryable=True,
                )
            except (OutputExpiredError, NotFoundError):
                if latest.status == "cancelled":
                    return latest
                return self._save(
                    latest,
                    remote_call_id=remote_id,
                    status="expired",
                    error_code="remote.output_expired",
                    retryable=False,
                )
            if latest.status == "cancelled":
                return latest
            return self._save(
                latest,
                remote_call_id=remote_id,
                status="cancel_requested",
                error_code=None,
                retryable=True,
            )
        return self._save(
            latest,
            remote_call_id=remote_id,
            status="running",
            error_code=None,
            retryable=True,
        )

    def poll(self, job_id: str) -> dict[str, object]:
        with self._submission_lock(job_id):
            return self._poll_locked(job_id)

    def _poll_locked(self, job_id: str) -> dict[str, object]:
        job = self.store.get(job_id)
        if job.status in _TERMINAL:
            return job.public()
        if job.prepare_call_id:
            job = self._poll_preparation(job)
            if job.status in _TERMINAL or job.prepare_call_id:
                return job.public()
        if not job.remote_call_id:
            if job.status == "cancel_requested":
                return job.public()
            if not job.input_path.startswith(CLIENT_INPUT_PREFIX):
                job = self._start_preparation(job)
                return job.public()
            job = self._bind(job)
            if not job.remote_call_id:
                return job.public()
        try:
            call = modal.FunctionCall.from_id(job.remote_call_id, client=client())
            value = call.get(timeout=0)
        except (ModalTimeoutError, TimeoutError):
            if job.status not in {"running", "cancel_requested"}:
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
            if job.status == "cancel_requested":
                return self._save(
                    job, status="cancelled", error_code="remote.cancelled", retryable=False
                ).public()
            return self._save(
                job, status="failed", error_code="remote.execution_failed", retryable=False
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
        result: dict[str, object] = {"artifact": descriptor}
        return self._save(
            job,
            status="succeeded",
            result=result,
            error_code=None,
            retryable=False,
        ).public()

    def cancel(self, job_id: str) -> dict[str, object]:
        with self._submission_lock(job_id):
            return self._cancel_locked(job_id)

    def _cancel_locked(self, job_id: str) -> dict[str, object]:
        job = self.store.get(job_id)
        if job.status in _TERMINAL:
            return job.public()
        if job.prepare_call_id and not job.remote_call_id:
            try:
                modal.FunctionCall.from_id(job.prepare_call_id, client=client()).cancel()
            except _RECOVERABLE:
                return self._save(
                    job,
                    status="connection_required",
                    error_code="modal.connection_required",
                    retryable=True,
                ).public()
            except (OutputExpiredError, NotFoundError):
                return self._save(
                    job,
                    prepare_call_id=None,
                    status="expired",
                    error_code="remote.preparation_expired",
                    retryable=False,
                ).public()
            return self._save(
                job,
                status="cancel_requested",
                error_code=None,
                retryable=True,
            ).public()
        if not job.remote_call_id:
            return self._save(
                job,
                status="cancel_requested",
                error_code=None,
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
        if all(getattr(job, key) == value for key, value in changes.items()):
            return job
        updated = replace(job, updated_at=_now(), **changes)
        self.store.save(updated)
        return updated
