from __future__ import annotations

import os
from pathlib import Path

import modal

SOURCE_FILE = Path(__file__).resolve()
ROOT = SOURCE_FILE.parents[3] if len(SOURCE_FILE.parents) > 3 else Path("/opt/src")
APP_NAME = "modal-studio-api"
DATA_DIR = "/data"
SOURCE_IGNORE = [
    ".venv",
    ".venv/**",
    ".venv-*",
    ".venv-*/**",
    "__pycache__",
    "**/__pycache__/**",
    ".git",
    ".git/**",
]

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "fastapi>=0.116,<1",
        "httpx>=0.28,<1",
        "modal[api-proxy-support]>=1.5,<2",
        "uvicorn>=0.35,<1",
        "PyJWT[crypto]>=2.10,<3",
        "jsonschema>=4.23,<5",
        "pydantic>=2.11,<3",
        "numpy>=2,<3",
        "pillow>=11,<13",
        "python-multipart",
        "scipy>=1.16,<2",
    )
    .add_local_dir(ROOT / "modal-2D", "/opt/src/modal-2D", copy=True, ignore=SOURCE_IGNORE)
    .add_local_dir(ROOT / "modal-3D", "/opt/src/modal-3D", copy=True, ignore=SOURCE_IGNORE)
    .add_local_dir(ROOT / "modal-world", "/opt/src/modal-world", copy=True, ignore=SOURCE_IGNORE)
    .add_local_dir(ROOT / "modal-build", "/opt/src/modal-build", copy=True, ignore=SOURCE_IGNORE)
    .add_local_dir(
        ROOT / "modal-2D-client", "/opt/src/modal-2D-client", copy=True, ignore=SOURCE_IGNORE
    )
    .add_local_dir(
        ROOT / "modal-3D-client", "/opt/src/modal-3D-client", copy=True, ignore=SOURCE_IGNORE
    )
    .add_local_dir(
        ROOT / "modal-gen-client", "/opt/src/modal-gen-client", copy=True, ignore=SOURCE_IGNORE
    )
    .env({
        "STUDIO_AUTH_MODE": "access",
        "STUDIO_ACCESS_ISSUER": "https://seachen.cloudflareaccess.com",
        "STUDIO_ACCESS_AUD": "bc0778bfd5613aecb806ad1f1055f3f591c2ec5ed5a2aa7a9f06cb2c09ce2a56",
        "STUDIO_ALLOWED_ORIGINS": "https://modal-studio.wangran.workers.dev",
        "STUDIO_REQUIRE_EDGE_SECRET": "0",
        "STUDIO_CONNECT_MODAL": "1",
        "MODAL_GEN_DATA_DIR": DATA_DIR,
    })
    .run_commands(
        "python -m pip install --no-deps /opt/src/modal-2D",
        "python -m pip install --no-deps /opt/src/modal-3D",
        "python -m pip install --no-deps /opt/src/modal-world",
        "python -m pip install --no-deps /opt/src/modal-build",
        "python -m pip install --no-deps /opt/src/modal-2D-client",
        "python -m pip install --no-deps /opt/src/modal-3D-client",
        "python -m pip install --no-deps /opt/src/modal-gen-client",
    )
)

data = modal.Volume.from_name("modal-studio-data", create_if_missing=True)
app = modal.App(APP_NAME)


@app.function(
    image=image,
    volumes={DATA_DIR: data},
    timeout=3600,
    max_containers=1,
    scaledown_window=300,
)
@modal.asgi_app()
def web():
    os.environ["MODAL_GEN_DATA_DIR"] = DATA_DIR
    os.environ.setdefault("STUDIO_CONNECT_MODAL", "1")
    from modal_gen.studio.app import create_app

    return create_app(persist=data.commit)
