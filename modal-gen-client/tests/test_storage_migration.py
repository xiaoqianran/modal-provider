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
    assert version == 2
    assert "provider_state_json" in columns
