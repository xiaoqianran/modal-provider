"""Single-instance product persistence and optional immutable R2 archive."""

from __future__ import annotations

import json
import os
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


class R2Archive:
    def __init__(self):
        import boto3
        from botocore.config import Config

        self.bucket = os.environ["STUDIO_R2_BUCKET"]
        self.client = boto3.client(
            "s3",
            endpoint_url=os.environ["STUDIO_R2_ENDPOINT"],
            region_name="auto",
            aws_access_key_id=os.environ["STUDIO_R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["STUDIO_R2_SECRET_ACCESS_KEY"],
            config=Config(signature_version="s3v4"),
        )

    @staticmethod
    def key(owner, artifact):
        return f"studio/{owner}/{artifact['id']}/{artifact['hash'][7:]}"

    def put(self, owner, artifact, path):
        self.client.upload_file(
            str(path),
            self.bucket,
            self.key(owner, artifact),
            ExtraArgs={"ContentType": artifact["mime"]},
        )

    def restore(self, owner, artifact, path):
        import tempfile
        from pathlib import Path

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".r2-")
        os.close(fd)
        temporary = Path(name)
        try:
            self.client.download_file(self.bucket, self.key(owner, artifact), str(temporary))
            from ..artifacts import ArtifactService

            ArtifactService._validate_file(temporary, artifact)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def url(self, owner, artifact):
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self.key(owner, artifact)},
            ExpiresIn=300,
        )
