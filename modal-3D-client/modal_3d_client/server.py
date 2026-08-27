from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = "127.0.0.1"
    configured = os.environ.get("MODAL_3D_CLIENT_HOST")
    if configured and configured != host:
        raise RuntimeError("modal-3D-client only listens on 127.0.0.1")
    port = int(os.environ.get("MODAL_3D_CLIENT_PORT", "3213"))
    uvicorn.run("modal_3d_client.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
