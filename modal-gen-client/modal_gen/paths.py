from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    configured = os.environ.get("MODAL_GEN_DATA_DIR")
    root = Path(configured).expanduser() if configured else Path.home() / ".modal-gen-client"
    root.mkdir(parents=True, exist_ok=True)
    return root


def database_path() -> Path:
    return data_dir() / "connector.sqlite3"


def artifact_cache_dir() -> Path:
    path = data_dir() / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path
