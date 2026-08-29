from __future__ import annotations

import os
import sys

import uvicorn

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main() -> None:
    """Start the Connector.

    Binding defaults to all interfaces for container/CNB port forwarding.
    Requests remain protected by the local control/session tokens.
    """
    host = os.environ.get("MODAL_GEN_HOST") or "0.0.0.0"
    if host not in _LOOPBACK_HOSTS:
        print(
            "警告：Connector 正监听非 loopback 地址 "
            f"{host!r}。配对、会话与产物将暴露到网络；请仅在受信任网络中使用。",
            file=sys.stderr,
        )
    port = int(os.environ.get("MODAL_GEN_PORT", "48123"))
    uvicorn.run("modal_gen.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
