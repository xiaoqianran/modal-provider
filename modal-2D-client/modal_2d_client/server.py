from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("MODAL_2D_HOST", "127.0.0.1")
    port = int(os.environ.get("MODAL_2D_PORT", "3212"))
    uvicorn.run("modal_2d_client.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
