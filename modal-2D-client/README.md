# modal-2D-client

`modal-2D-client` 是 `modal-2D` 的 **Reference Sidecar**：把远端 Modal execution 映射成本地可恢复 Job，并负责验证/缓存 Provider Artifact。它没有业务 UI，也不拥有 Asset、World 或全局 Provider routing；`modal-gen-client` 如存在，只把它当作安全 transport 下游。

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
        ┌───────┴────────┐
        ▼                ▼
Sana Sprint Worker   Artifact Volume
                         │
                         └── Volume-first → 本地 cache
```

## Provider Agent API

这里的 `/v1/*` 是 **modal-2D 本地 Provider Agent API**，不是 Unified Connector 的 `/connector/v1/*`。Connector 应通过薄 adapter 消费这些本地事实，再由 Connector 自己拥有全局 Job identity、event sequence、session/scope 与统一 Artifact identity。

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
- `GET /v1/jobs/{id}/artifacts/{index}`

## 设计原则

- Modal token 只驻留进程内存，不写 SQLite、不写日志、不进入 Job。
- SQLite 只保存可恢复 Job 镜像和 `remote_call_id`。
- 成功 Job 先返回远端 Artifact descriptor；PNG 只有被读取时才下载。Batch Job 使用同一个 `remote_call_id` 保存 `artifacts[]`，不新增第二套 Job lifecycle。
- Artifact 读取优先走 `modal-2d-artifacts` 命名 Volume；旧 `read_artifact` Function 只做 transport fallback。
- Volume 数据按 chunk 写入临时文件，同时校验 PNG magic / bytes / SHA-256；验证成功后才原子进入内容寻址 cache。完整性失败不会 fallback 掩盖。
- Client 独立校验云端 capability，不信任 Provider 返回。
- SANA-Sprint 固定使用 2 steps；本地 API 不暴露无效的 steps 调节参数。
- 支持一个逻辑 Job 携带 `seeds[]` 的 Provider batch capability，但没有 Project、Web Studio、ledger 或 batch scheduler。

## 本地运行

```bash
uv sync --dev
uv run pytest -q
uv run modal-2d-agent
```

默认仅监听 `127.0.0.1:3212`，外部 bind 会直接拒绝。设置 `MODAL_2D_AGENT_TOKEN` 后，所有非 `OPTIONS` 请求必须携带 `X-Modal-2D-Session`；token 只从环境进入进程，不写 Job/SQLite/响应。Artifact 响应携带 `ETag`、`X-Artifact-ID`、`X-Artifact-SHA256`，便于上层 adapter 做不可变内容校验。

## 与 modal-gen-client 的边界

```text
Browser / WebView
      │
      ▼
modal-gen-client
  pairing / origin / scope / credential isolation
      │
      ▼
modal-2D-client
  local job mirror / artifact verification / cache
      │
      ▼
modal-2D
  model / GPU / remote artifact
```

`modal-gen-client` 不吸收本仓的 Provider-specific Job/Artifact implementation；它只通过本地 API 做安全 transport。这样本仓可以继续脱离 AgentScape 独立 smoke 和恢复测试。


## Candidate Batch

同一个 prompt 的多个 seed 应作为一个逻辑 Job 提交：

```json
{
  "prompt": "a glossy red apple",
  "model": "sana-sprint-1.6b",
  "seeds": [42, 73, 104, 135]
}
```

Sidecar 只创建一个本地 Job / 一个 Modal `FunctionCall`；Provider 返回 `artifacts[]` 后，可通过 `/v1/jobs/{id}/artifacts/{index}` 按索引验证并读取每个 PNG。取消、恢复、SQLite 镜像与单图 Job 共用同一套状态机。
