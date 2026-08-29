import sqlite3
from pathlib import Path

from modal_gen.storage import Store


def test_v1_database_migrates_provider_state_column(tmp_path: Path):
    path = tmp_path / "connector.sqlite3"
    db = sqlite3.connect(path)
    try:
        db.executescript(
            """
            PRAGMA user_version = 1;
            CREATE TABLE jobs (
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
            """
        )
        db.commit()
    finally:
        db.close()

    Store(path)

    db = sqlite3.connect(path)
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
    finally:
        db.close()
    assert version == 3
    assert "provider_state_json" in columns


def test_v2_artifact_role_identity_migrates_to_provider_artifact_identity(tmp_path: Path):
    path = tmp_path / "connector.sqlite3"
    Store(path)
    db = sqlite3.connect(path)
    try:
        db.executescript(
            """
            DROP INDEX IF EXISTS artifacts_job_idx;
            DROP TABLE artifacts;
            CREATE TABLE artifacts (
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
            CREATE INDEX artifacts_job_idx ON artifacts(job_id);
            PRAGMA user_version = 2;
            """
        )
        db.commit()
    finally:
        db.close()

    Store(path)

    db = sqlite3.connect(path)
    try:
        unique = []
        for row in db.execute("PRAGMA index_list(artifacts)"):
            if row[2]:
                columns = tuple(item[2] for item in db.execute(f"PRAGMA index_info({row[1]!r})"))
                unique.append(columns)
    finally:
        db.close()
    assert ("job_id", "provider_artifact_id") in unique
    assert ("job_id", "role") not in unique
