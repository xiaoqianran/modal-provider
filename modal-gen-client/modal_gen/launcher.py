from __future__ import annotations

import os
import threading


def main() -> None:
    """Start the Connector and bundled console with one command."""
    connector_host = os.environ.get("MODAL_GEN_HOST") or "0.0.0.0"
    connector_port = int(os.environ.get("MODAL_GEN_PORT", "48123"))
    os.environ.setdefault("MODAL_GEN_CONNECTOR_URL", f"http://127.0.0.1:{connector_port}")

    from . import server
    from .ui import server as ui_server

    thread = threading.Thread(
        target=ui_server.main,
        name="modal-gen-ui",
        daemon=True,
    )
    thread.start()

    # Connector remains the foreground process so Ctrl+C and process supervisors
    # keep their normal uvicorn semantics. The UI thread exits with this process.
    os.environ.setdefault("MODAL_GEN_HOST", connector_host)
    server.main()


if __name__ == "__main__":
    main()
