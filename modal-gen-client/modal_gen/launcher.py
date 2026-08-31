from __future__ import annotations

import os
import socket
import sys
import threading


def _port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _require_available_port(label: str, host: str, port: int) -> None:
    if _port_available(host, port):
        return
    print(
        f"modal-gen 未启动：{label} 端口 {host}:{port} 已被占用。"
        "如果 modal-gen 已在运行，请直接使用现有实例；否则先关闭占用该端口的进程。",
        file=sys.stderr,
    )
    raise SystemExit(2)


def main() -> None:
    """Start the Connector and bundled console with one command."""
    connector_host = os.environ.get("MODAL_GEN_HOST") or "0.0.0.0"
    connector_port = int(os.environ.get("MODAL_GEN_PORT", "48123"))
    ui_host = os.environ.get("MODAL_GEN_UI_HOST") or "0.0.0.0"
    ui_port = int(os.environ.get("MODAL_GEN_UI_PORT", "48124"))

    # Fail before starting the UI thread or FastAPI lifespan. This avoids partial
    # startup and credential-restore cancellation when another instance owns a port.
    _require_available_port("Connector", connector_host, connector_port)
    _require_available_port("控制台", ui_host, ui_port)

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
