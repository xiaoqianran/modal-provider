from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    configured = os.environ.get("MODAL_2D_DATA_DIR")
    root = Path(configured).expanduser() if configured else Path.home() / ".modal-2d-client"
    root.mkdir(parents=True, exist_ok=True)
    return root
