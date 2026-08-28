# modal-gen-client

`modal-gen-client` 是本地统一生成 Connector。它面向 AgentScape 暴露稳定的 `/connector/v1/*`，向下通过 Provider Adapter 连接 `modal-2D-client`、`modal-3D-client`，以后也可以扩展 `modal-world`、`modal-music` 等 Provider。

```text
AgentScape
    │
    │ /connector/v1/*
    ▼
modal-gen-client
├── Session / Pairing
├── Capability Registry
├── Unified Job Store
├── Unified Artifact Registry
└── Provider Adapters
    ├── modal-2D  ✅
    ├── modal-3D  ✅
    ├── modal-world
    └── modal-music
         │
         ▼
   Provider Agent
```

## 设计边界

- Connector 拥有全局 Job identity、idempotency、session/scope、capability snapshot 与统一 Artifact identity。
- Provider Agent 拥有 Provider 私有 Job、私有 Artifact 与模型运行事实；Connector 不复制模型业务。
- Provider Artifact ID 不暴露为统一 Artifact ID；SHA-256 只做完整性与内容缓存，不做业务 identity。
- Connector 不依赖 Modal SDK。`modal-2D` / `modal-3D` adapter 都只通过各自 Provider Agent 的 loopback HTTP API 工作。
- Artifact 从 Provider 到 Connector 采用流式复制、增量 SHA-256、大小/chunk 上限、内容前缀校验、fsync 与原子发布。

## Connector API

```text
POST   /connector/v1/session
DELETE /connector/v1/session
GET    /connector/v1/capabilities
GET    /connector/v1/jobs
POST   /connector/v1/jobs
GET    /connector/v1/jobs/{id}
POST   /connector/v1/jobs/{id}/cancel
GET    /connector/v1/artifacts/{id}
```

Session 绑定 client identity、origin、scope、expiry 和 capability hash/revision。明文 Bearer token 只在 pairing 成功时返回一次；SQLite 只持久化 token hash。

## 本地控制面

```text
GET  /health
GET  /v1/providers
GET  /v1/capabilities
GET  /v1/pairings
POST /v1/pairings/{id}/approve
```

`/v1/*` 默认锁死。必须配置 `MODAL_GEN_AGENT_TOKEN`，并通过 `X-Modal-Gen-Session` 访问本地控制面。服务强制监听 `127.0.0.1`。

```bash
export MODAL_GEN_AGENT_TOKEN='本地随机会话值'
uv run modal-gen-agent
```

默认端口 `48123`，可以用 `MODAL_GEN_PORT` 修改。

## 网络暴露（默认仅 loopback）

Connector 持有配对批准、会话 token 与产物字节，因此**默认只监听 `127.0.0.1`**，
且 CORS 只回显已配对的 Origin。需要局域网/其他域名访问时，用下面两个变量**显式开启**：

```bash
export MODAL_GEN_HOST=0.0.0.0            # 监听所有网卡
export MODAL_GEN_ALLOW_ANY_ORIGIN=1      # CORS 回显 *，不再按 Origin 拒绝
uv run modal-gen-agent
```

控制台同理：

```bash
export MODAL_GEN_UI_HOST=0.0.0.0
export MODAL_GEN_ALLOW_ANY_ORIGIN=1
uv run python -m modal_gen.ui.server
```

两者在非 loopback 监听时都会在 stderr 打印警告。**放开 Origin 边界不会削弱鉴权**：
无 token / 错误 token 仍然 `401`，`/v1/*` 控制面仍然要求 `MODAL_GEN_AGENT_TOKEN`，
配对批准仍然必须由本地控制面完成。请仅在受信任网络中使用。

## modal-2D Provider

默认 adapter 连接：

```text
http://127.0.0.1:3212
```

可通过 `MODAL_2D_AGENT_ENDPOINT` 指定其他 **loopback HTTP origin**。如果 `modal-2D-client` 启用了本地 session gate，则让两个进程共享 `MODAL_2D_AGENT_TOKEN`。

当前真实契约：

```text
provider:   modal-2d
operation:  modal-2d.image.text_to_image.v1
models:     sana-sprint-0.6b / sana-sprint-1.6b
profile:    recommended
input:      prompt / model / seed / guidance
runtime:    1024×1024 / 固定 2 steps
output:     primary-image / image/png
```

## modal-3D Provider

`modal-3D-client` 桌面 Agent 使用随机 loopback 端口与本地 session token，因此 Connector 不猜端口、不绕过 session。当前通过下列变量显式桥接：

```bash
export MODAL_3D_AGENT_ENDPOINT='http://127.0.0.1:<当前 Agent 端口>'
export MODAL_3D_AGENT_TOKEN='当前本地 Agent session'
```

未配置 endpoint 时，`modal-3d` 会保留在 provider registry 中但 capability 标记为 unavailable；不会伪装可用。
本地 BiRefNet preprocess 模型也必须处于 `ready + verified`；未准备完成时同样 fail closed 为 unavailable。

当前稳定 operation：

```text
provider:   modal-3d
operation:  modal-3d.asset.image_to_3d.v1
models:     GET /v1/models 动态发现，不在 Connector 硬编码
profile:    recommended
input:      sourceArtifact{id,role,mime,hash} / model / seed
source:     primary-image / image/png
flow:       project → preprocess → canonical RGBA → generation
output:     primary-glb / model/gltf-binary
```

`sourceArtifact.id` 是 Connector 全局 Artifact ID。Adapter 只通过当前 session 的 ArtifactResolver 取得本地已校验内容，再上传给 3D Agent；2D provider 私有 Artifact ID 与路径不会跨 Provider 泄漏。Provider-private `projectId` 只持久化在 Connector DB，用于重启恢复，不进入 AgentScape Job projection。

## Pairing

AgentScape 第一次调用 `/connector/v1/session` 会得到 `approval_required + pairingId`。用户必须通过受本地 token 保护的控制面批准该 pairing，随后 AgentScape 再次提交同一个 pairingId 才能获得 scoped session。

这意味着网页不能仅凭跨站请求自行批准本地 Connector 权限。

## 本地控制台 UI

`modal_gen.ui` 提供一个只读/操作型的本地 Web 控制台，独立进程运行，**不**与
`/connector/v1/*` 共用端口。它消费同一份 Connector 契约，不复制 Provider 业务。

```bash
# 演示模式：无需 Connector / Modal 账号即可打开界面
MODAL_GEN_UI_DEMO=1 uv run python -m modal_gen.ui.server

# 实连模式：连接本机 Connector（需先启动 modal-gen-agent）
export MODAL_GEN_AGENT_TOKEN='本地随机会话值'
uv run python -m modal_gen.ui.server
```

打开 http://127.0.0.1:48124/ui/ 。默认端口 `48124`（`MODAL_GEN_UI_PORT` 可改）。

实连模式下控制台以 `agentscape` 身份执行真实两段式 pairing：先请求配对得到
`pairingId`，再通过 Connector 本地控制面批准，最后换取 scoped bearer session。
演示模式用 `DemoEngine` 提供能力快照与任务/产物样本，仅用于界面渲染与审查。

| 页面 | Primary Job |
| --- | --- |
| 连接 | 确认 Connector 与两个 Provider 可用；需要时批准配对 |
| 创建 | 从实时能力快照生成表单并提交一次生成任务 |
| 任务 | 跟踪任务到终态，必要时取消或查看详情 |
| 产物 | 下载并校验 SHA-256，确认内容完整 |

界面审查（Render → Critique → Fix）使用 Playwright 实际运行并截图：

```bash
node modal_gen/ui/review.mjs         # 四个页面 + 3D 不可用 + 移动端
node modal_gen/ui/review_states.mjs  # 校验 / 离线 / 空态 / loading / 哈希校验
```

## 开发

```bash
uv sync --dev
uv run ruff check .
uv run ruff format . --check
uv run python -m compileall -q modal_gen tests
uv run pytest -q
uv build
```

第一版没有 UI，也不复制 `modal-3D-client` 的模型业务。2D/3D 都已作为独立 Provider Adapter 接入统一 Connector；后续优先解决桌面 Agent endpoint/session 的安全自动发现，再逐步把通用 client 能力收敛进单一 `modal-gen-client` 产品。
