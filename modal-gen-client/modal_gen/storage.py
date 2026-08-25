from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .paths import database_path

_DB_VERSION = 1


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _init_db(self) -> None:
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > _DB_VERSION:
                raise RuntimeError(f"Connector DB version is newer than supported: {version}")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capability_snapshots (
                    hash TEXT PRIMARY KEY,
                    revision TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pairings (
                    id TEXT PRIMARY KEY,
                    client_identity TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_id TEXT PRIMARY KEY,
                    token_hash TEXT UNIQUE NOT NULL,
                    client_identity TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    capability_revision TEXT NOT NULL,
                    capability_hash TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    owner_client TEXT NOT NULL,
                    owner_origin TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    contract_version TEXT NOT NULL,
                    capability_hash TEXT NOT NULL,
                    capability_revision TEXT NOT NULL,
                    provider_job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT,
                    attempt INTEGER NOT NULL,
                    relations_json TEXT NOT NULL,
                    effective_options_json TEXT NOT NULL,
                    model_json TEXT,
                    created_at TEXT NOT NULL,
                    submitted_at TEXT,
                    started_at TEXT,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    error_json TEXT,
                    result_json TEXT,
                    event_sequence INTEGER NOT NULL,
                    UNIQUE(owner_client, owner_origin, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    mime TEXT NOT NULL,
                    bytes INTEGER NOT NULL,
                    hash TEXT NOT NULL,
                    provider_artifact_id TEXT NOT NULL,
                    provider_job_id TEXT NOT NULL,
                    UNIQUE(job_id, role),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS jobs_owner_idx
                    ON jobs(owner_client, owner_origin, created_at);
                CREATE INDEX IF NOT EXISTS artifacts_job_idx ON artifacts(job_id);
                """
            )
            db.execute(f"PRAGMA user_version = {_DB_VERSION}")

    def instance_id(self) -> str:
        with self._lock, self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='instance_id'").fetchone()
            if row:
                return str(row["value"])
            value = f"instance_{uuid.uuid4().hex}"
            db.execute("INSERT INTO metadata(key,value) VALUES('instance_id',?)", (value,))
            return value

    def save_snapshot(self, snapshot: dict[str, object]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO capability_snapshots(hash,revision,snapshot_json,expires_at)
                VALUES(?,?,?,?)
                ON CONFLICT(hash) DO UPDATE SET
                    revision=excluded.revision,
                    snapshot_json=excluded.snapshot_json,
                    expires_at=excluded.expires_at
                """,
                (
                    snapshot["hash"],
                    snapshot["revision"],
                    _dump(snapshot),
                    snapshot["expiresAt"],
                ),
            )

    def get_snapshot(self, hash_value: str) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT snapshot_json FROM capability_snapshots WHERE hash=?", (hash_value,)
            ).fetchone()
        return json.loads(row["snapshot_json"]) if row else None

    def create_pairing(self, row: dict[str, object]) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO pairings VALUES(?,?,?,?,?,?,?)",
                (
                    row["id"],
                    row["client_identity"],
                    row["origin"],
                    _dump(row["scopes"]),
                    row["status"],
                    row["created_at"],
                    row["expires_at"],
                ),
            )

    def get_pairing(self, pairing_id: str) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM pairings WHERE id=?", (pairing_id,)).fetchone()
        return _pairing(row) if row else None

    def set_pairing_status(self, pairing_id: str, status: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE pairings SET status=? WHERE id=?", (status, pairing_id))

    def list_pairings(self) -> list[dict[str, object]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM pairings ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [_pairing(row) for row in rows]

    def create_session(self, row: dict[str, object]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO sessions(
                    token_id,token_hash,client_identity,origin,scopes_json,issued_at,expires_at,
                    capability_revision,capability_hash,revoked
                ) VALUES(?,?,?,?,?,?,?,?,?,0)
                """,
                (
                    row["token_id"],
                    row["token_hash"],
                    row["client_identity"],
                    row["origin"],
                    _dump(row["scopes"]),
                    row["issued_at"],
                    row["expires_at"],
                    row["capability_revision"],
                    row["capability_hash"],
                ),
            )

    def get_session_by_hash(self, token_hash: str) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE token_hash=?", (token_hash,)).fetchone()
        return _session(row) if row else None

    def revoke_session(self, token_id: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE sessions SET revoked=1 WHERE token_id=?", (token_id,))

    def find_job_by_idempotency(
        self, owner_client: str, owner_origin: str, idempotency_key: str
    ) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT * FROM jobs
                WHERE owner_client=? AND owner_origin=? AND idempotency_key=?
                """,
                (owner_client, owner_origin, idempotency_key),
            ).fetchone()
        return _job(row) if row else None

    def create_job(self, row: dict[str, object]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO jobs(
                    id,owner_client,owner_origin,provider,operation,request_hash,idempotency_key,
                    contract_version,capability_hash,capability_revision,provider_job_id,status,stage,
                    attempt,relations_json,effective_options_json,model_json,created_at,submitted_at,
                    started_at,updated_at,completed_at,error_json,result_json,event_sequence
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                _job_values(row),
            )

    def get_job(
        self, job_id: str, owner_client: str, owner_origin: str
    ) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE id=? AND owner_client=? AND owner_origin=?",
                (job_id, owner_client, owner_origin),
            ).fetchone()
        return _job(row) if row else None

    def list_jobs(self, owner_client: str, owner_origin: str) -> list[dict[str, object]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM jobs WHERE owner_client=? AND owner_origin=?
                ORDER BY created_at DESC LIMIT 200
                """,
                (owner_client, owner_origin),
            ).fetchall()
        return [_job(row) for row in rows]

    def update_job(self, row: dict[str, object]) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE jobs SET
                    status=?,stage=?,relations_json=?,effective_options_json=?,model_json=?,
                    started_at=?,updated_at=?,completed_at=?,error_json=?,result_json=?,event_sequence=?
                WHERE id=?
                """,
                (
                    row["status"],
                    row.get("stage"),
                    _dump(row.get("relations") or []),
                    _dump(row.get("effective_options") or {}),
                    _dump(row["model"]) if row.get("model") else None,
                    row.get("started_at"),
                    row["updated_at"],
                    row.get("completed_at"),
                    _dump(row["error"]) if row.get("error") else None,
                    _dump(row["result"]) if row.get("result") else None,
                    row["event_sequence"],
                    row["id"],
                ),
            )

    def create_artifact(self, row: dict[str, object]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO artifacts(
                    id,job_id,role,mime,bytes,hash,provider_artifact_id,provider_job_id
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    row["id"],
                    row["job_id"],
                    row["role"],
                    row["mime"],
                    row["bytes"],
                    row["hash"],
                    row["provider_artifact_id"],
                    row["provider_job_id"],
                ),
            )

    def get_artifact_for_job(self, job_id: str, role: str) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM artifacts WHERE job_id=? AND role=?", (job_id, role)
            ).fetchone()
        return dict(row) if row else None

    def get_artifact(
        self, artifact_id: str, owner_client: str, owner_origin: str
    ) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT a.* FROM artifacts a
                JOIN jobs j ON j.id=a.job_id
                WHERE a.id=? AND j.owner_client=? AND j.owner_origin=?
                """,
                (artifact_id, owner_client, owner_origin),
            ).fetchone()
        return dict(row) if row else None


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _pairing(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "client_identity": row["client_identity"],
        "origin": row["origin"],
        "scopes": json.loads(row["scopes_json"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


def _session(row: sqlite3.Row) -> dict[str, object]:
    return {
        "token_id": row["token_id"],
        "token_hash": row["token_hash"],
        "client_identity": row["client_identity"],
        "origin": row["origin"],
        "scopes": json.loads(row["scopes_json"]),
        "issued_at": row["issued_at"],
        "expires_at": row["expires_at"],
        "capability_revision": row["capability_revision"],
        "capability_hash": row["capability_hash"],
        "revoked": bool(row["revoked"]),
    }


def _job(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "owner_client": row["owner_client"],
        "owner_origin": row["owner_origin"],
        "provider": row["provider"],
        "operation": row["operation"],
        "request_hash": row["request_hash"],
        "idempotency_key": row["idempotency_key"],
        "contract_version": row["contract_version"],
        "capability_hash": row["capability_hash"],
        "capability_revision": row["capability_revision"],
        "provider_job_id": row["provider_job_id"],
        "status": row["status"],
        "stage": row["stage"],
        "attempt": row["attempt"],
        "relations": json.loads(row["relations_json"]),
        "effective_options": json.loads(row["effective_options_json"]),
        "model": json.loads(row["model_json"]) if row["model_json"] else None,
        "created_at": row["created_at"],
        "submitted_at": row["submitted_at"],
        "started_at": row["started_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
        "error": json.loads(row["error_json"]) if row["error_json"] else None,
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "event_sequence": row["event_sequence"],
    }


def _job_values(row: dict[str, object]) -> tuple[object, ...]:
    return (
        row["id"],
        row["owner_client"],
        row["owner_origin"],
        row["provider"],
        row["operation"],
        row["request_hash"],
        row["idempotency_key"],
        row["contract_version"],
        row["capability_hash"],
        row["capability_revision"],
        row["provider_job_id"],
        row["status"],
        row.get("stage"),
        row["attempt"],
        _dump(row.get("relations") or []),
        _dump(row.get("effective_options") or {}),
        _dump(row["model"]) if row.get("model") else None,
        row["created_at"],
        row.get("submitted_at"),
        row.get("started_at"),
        row["updated_at"],
        row.get("completed_at"),
        _dump(row["error"]) if row.get("error") else None,
        _dump(row["result"]) if row.get("result") else None,
        row["event_sequence"],
    )
