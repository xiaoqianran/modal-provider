"""Versioned stage checkpoint manifests and input fingerprints.

Pure filesystem helpers: no Modal/GPU imports.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1

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
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path
