from __future__ import annotations

import os

import uvicorn


def main() -> None:
    # Bind on all interfaces by default so the sidecar is reachable from a
    # container network / public proxy. Set MODAL_3D_CLIENT_HOST to narrow it.
    host = os.environ.get("MODAL_3D_CLIENT_HOST", "0.0.0.0")
    port = int(os.environ.get("MODAL_3D_CLIENT_PORT", "3213"))
    uvicorn.run("modal_3d_client.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
