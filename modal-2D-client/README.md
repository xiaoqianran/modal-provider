# modal-2D-client

`modal-2D-client` 是 `modal-2D` 的本地薄 Agent。它没有独立桌面 UI；未来 2D 与 3D 会统一进入 `modal-gen-client`，因此本仓从一开始就把 UI 和 Provider Agent 解耦。

```text
本地 UI / Connector（未来 modal-gen-client）
                │
                ▼
        modal-2D-client Agent
                │
      ┌─────────┼──────────┐
      │         │          │
   Session   Job mirror  Artifact cache
      │         │          │
      └─────────┼──────────┘
                ▼
             Modal
                │
                ▼
           modal-2D
                │
                ▼
       Sana Sprint GPU Worker
```

## API

- `GET /health`
- `GET /modal/status`
- `POST /modal/connect` / `DELETE /modal/connect`
- `GET /v1/capabilities`
- `GET /v1/models`
- `GET /v1/jobs`
- `POST /v1/jobs`
- `GET /v1/jobs/{id}`
- `DELETE /v1/jobs/{id}`
- `GET /v1/jobs/{id}/artifact`

## 设计原则

- Modal token 只驻留进程内存，不写 SQLite、不写日志、不进入 Job。
- SQLite 只保存可恢复 Job 镜像和 `remote_call_id`。
- 成功 Job 先返回远端 Artifact descriptor；PNG 只有被读取时才下载。
- Artifact 缓存按 SHA-256 内容寻址，下载后校验 PNG magic / bytes / SHA-256，再原子落盘。
- Client 独立校验云端 capability，不信任 Provider 返回。
- 没有 Project、Web Studio、ledger、batch scheduler 等 2D Provider 不需要的概念。

## 本地运行

```bash
uv sync --dev
uv run pytest -q
uv run modal-2d-agent
```

默认仅监听 `127.0.0.1:3212`。

## 未来合并到 modal-gen-client

```text
modal-gen-client
├── common/          # session / jobs / artifact cache
├── providers/
│   ├── modal_2d/    # 本仓 provider-specific capability + request
│   ├── modal_3d/
│   ├── modal_world/
│   └── modal_music/
└── ui/              # 唯一统一 UI
```

本仓的职责就是让未来迁移变成“移动模块”，而不是“重写应用”。
