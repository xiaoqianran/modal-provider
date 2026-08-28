from __future__ import annotations

import os
import tempfile
from pathlib import Path

_APP_DIR = "modal-3D-client"


def data_dir() -> Path:
    override = os.environ.get("MODAL_3D_CLIENT_DATA_DIR")
    if override:
        root = Path(override)
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / _APP_DIR
    elif os.environ.get("XDG_DATA_HOME"):
        root = Path(os.environ["XDG_DATA_HOME"]) / _APP_DIR
    else:
        try:
            root = Path.home() / ".local" / "share" / _APP_DIR
        except (OSError, RuntimeError):
            root = Path(tempfile.gettempdir()) / _APP_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root
