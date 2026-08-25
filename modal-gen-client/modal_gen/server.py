from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = "127.0.0.1"
    configured_host = os.environ.get("MODAL_GEN_HOST")
    if configured_host and configured_host != host:
        raise RuntimeError("modal-gen Connector 只允许监听 127.0.0.1")
    port = int(os.environ.get("MODAL_GEN_PORT", "48123"))
    uvicorn.run("modal_gen.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
