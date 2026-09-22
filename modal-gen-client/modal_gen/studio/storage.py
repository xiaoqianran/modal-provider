"""Single-instance product persistence for Studio metadata and intent state."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager


class StudioStore:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    created TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS records_owner ON records(kind, owner, created);
                CREATE TABLE IF NOT EXISTS requests (
                    owner TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL,
                    job_id TEXT NOT NULL, PRIMARY KEY(owner, key));
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, kind, owner, value):
        with self.db() as db:
            db.execute(
                "INSERT INTO records VALUES (?,?,?,?,?) ON CONFLICT(id) "
                "DO UPDATE SET payload=excluded.payload",
                (kind, value["id"], owner, value["createdAt"], json.dumps(value)),
            )
        return value

    def get(self, kind, owner, item_id):
        with self.db() as db:
            row = db.execute(
                "SELECT payload FROM records WHERE kind=? AND owner=? AND id=?",
                (kind, owner, item_id),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind, owner=None, limit=200):
        with self.db() as db:
            if owner is None:
                rows = db.execute(
                    "SELECT owner,payload FROM records WHERE kind=? ORDER BY created DESC", (kind,)
                ).fetchall()
                return [(r[0], json.loads(r[1])) for r in rows]
            rows = db.execute(
                "SELECT payload FROM records WHERE kind=? AND owner=? "
                "ORDER BY created DESC LIMIT ?",
                (kind, owner, limit),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def reserve(self, owner, key, digest, job):
        # Persist intent and its idempotency mapping in one transaction before dispatch.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            found = db.execute(
                "SELECT digest,job_id FROM requests WHERE owner=? AND key=?", (owner, key)
            ).fetchone()
            if found:
                return found
            db.execute("INSERT INTO requests VALUES (?,?,?,?)", (owner, key, digest, job["id"]))
            db.execute(
                "INSERT INTO records VALUES (?,?,?,?,?)",
                ("job", job["id"], owner, job["createdAt"], json.dumps(job)),
            )
        return digest, job["id"]
