"""Versioned stage checkpoint manifests and input fingerprints.

Pure filesystem helpers: no Modal/GPU imports.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.Lock] = {}


@contextmanager
def _manifest_write_lock(path: Path):
    """Serialize writers in this process; readers still use atomic replacement."""
    key = path.resolve()
    with _LOCKS_GUARD:
        lock = _PATH_LOCKS.setdefault(key, threading.Lock())
    with lock:
        yield

def fingerprint_files(paths: Iterable[Path], *, root: Path) -> str:
    """Hash names, sizes, and bytes so resume is invalidated when upstream data changes."""
    digest = hashlib.sha256()
    files = sorted((Path(path) for path in paths), key=lambda path: str(path))
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = path
        digest.update(str(relative).encode())
        stat = path.stat()
        digest.update(str(stat.st_size).encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def build_stage_manifest(
    *,
    job_id: str,
    stage: str,
    hyworld_revision: str,
    input_fingerprint: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "job_id": job_id,
        "stage": stage,
        "hyworld_revision": hyworld_revision,
        "input_fingerprint": input_fingerprint,
        "config": config,
    }


def stage_manifest_path(target: Path, stage: str) -> Path:
    return target / ".modal-world" / f"{stage}.json"


def manifest_matches(target: Path, stage: str, expected: dict[str, Any]) -> bool:
    path = stage_manifest_path(target, stage)
    if not path.is_file():
        return False
    try:
        actual = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return actual == expected


def write_stage_manifest(target: Path, stage: str, manifest: dict[str, Any]) -> Path:
    path = stage_manifest_path(target, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with _manifest_write_lock(path):
        temporary: Path | None = None
        try:
            # Same directory/filesystem: readers see either complete old or new JSON.
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{path.name}.", suffix=".tmp",
                dir=path.parent, delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            # Windows readers can briefly hold a no-delete file handle.
            for attempt in range(12):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if os.name != "nt" or attempt == 11:
                        raise
                    time.sleep(0.01)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return path
