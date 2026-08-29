from __future__ import annotations

import os
import sys

import uvicorn

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main() -> None:
    """Start the Connector.

    Binding is loopback-only by default because the Connector holds pairing
    approvals, session tokens and artifact bytes. Exposing it on `0.0.0.0`
    is supported but must be requested explicitly with `MODAL_GEN_HOST`.
    """
    host = os.environ.get("MODAL_GEN_HOST") or "127.0.0.1"
    if host not in _LOOPBACK_HOSTS:
        if not os.environ.get("MODAL_GEN_AGENT_TOKEN"):
            raise SystemExit(
                "非 loopback 监听必须显式设置 MODAL_GEN_AGENT_TOKEN；"
                "默认本地 token 不允许暴露到网络。"
            )
        print(
            "警告：Connector 正监听非 loopback 地址 "
            f"{host!r}。配对、会话与产物将暴露到网络；请仅在受信任网络中使用。",
            file=sys.stderr,
        )
    port = int(os.environ.get("MODAL_GEN_PORT", "48123"))
    uvicorn.run("modal_gen.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
