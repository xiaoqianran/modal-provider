from __future__ import annotations

import os

import uvicorn

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 3212


def main() -> None:
    # 默认监听所有网卡：便于容器、局域网与反向代理访问。
    # 注意：本进程持有 Modal 凭据。暴露到不可信网络时请设置
    # MODAL_2D_AGENT_TOKEN，否则任何人都能提交任务并读取产物。
    host = os.environ.get("MODAL_2D_HOST") or DEFAULT_HOST
    port = int(os.environ.get("MODAL_2D_PORT") or DEFAULT_PORT)
    uvicorn.run("modal_2d_client.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
