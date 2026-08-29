# modal-2D-client

`modal-2D-client` 是 `modal-2D` 的 **Reference Sidecar**：把远端 Modal execution 映射成本地可恢复 Job，并负责验证/缓存 Provider Artifact。它没有业务 UI，也不拥有 Asset、World 或全局 Provider routing；`modal-gen-client` 如存在，只把它当作安全 transport 下游。

```text
AgentScape / optional modal-gen-client
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
- 提交时按 `model_id` 直接 lookup `SanaSprintWorker` 并 spawn `generate` / `generate_batch`，中间没有 CPU 中转 Function：Modal 每多一层 Function 就多一次独立冷启动，中转层会让首次请求先等 CPU 容器、再等 GPU 容器。
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

默认监听 `0.0.0.0:3212`（所有网卡），默认允许任意来源跨域访问。

```bash
MODAL_2D_HOST=127.0.0.1 MODAL_2D_PORT=4000 uv run modal-2d-agent   # 收窄到本机
MODAL_2D_CORS_ORIGINS="http://a.test,http://b.test" uv run modal-2d-agent
```

| 变量 | 默认 | 说明 |
|---|---|---|
| `MODAL_2D_HOST` | `0.0.0.0` | 绑定地址，可为任意值 |
| `MODAL_2D_PORT` | `3212` | 监听端口 |
| `MODAL_2D_CORS_ORIGINS` | `*` | 允许的来源，逗号分隔 |
| `MODAL_2D_AGENT_TOKEN` | 无 | 设置后所有非 `OPTIONS` 请求需携带 `X-Modal-2D-Session` |

**安全提示**：本进程持有 Modal 凭据。绑到 `0.0.0.0` 且未设置 `MODAL_2D_AGENT_TOKEN` 时，能访问该端口的任何人都可以用你的 Modal 额度提交任务、读取全部 Job 与产物、断开连接。暴露到不可信网络时请务必设置 token。

设置 token 后：所有非 `OPTIONS` 请求必须携带 `X-Modal-2D-Session`，token 只从环境进入进程，不写 Job/SQLite/响应；操作台的静态资源仍可匿名访问（浏览器导航无法携带自定义头），其发出的 XHR 受保护。Artifact 响应携带 `ETag`、`X-Artifact-ID`、`X-Artifact-SHA256`，并已加入 `Access-Control-Expose-Headers`，跨域调用也能读取。

## 操作台（Developer Console）

Agent 自带一个浏览器操作台，把上述每个端点暴露成一个可执行的步骤。它是**调试与教学工具**，不是产品界面——不拥有业务状态，也不替代 Connector。

打开 <http://127.0.0.1:3212/>（根路径 307 跳转到 `/ui/index.html`）。若从其他机器或容器访问，把 `127.0.0.1` 换成该主机的地址即可。

```text
1 连接 Modal     → /health · /modal/status · POST|DELETE /modal/connect
2 确认能力       → /v1/capabilities · /v1/models
3 提交 Job       → POST /v1/jobs（单张 seed 或批量 seeds）
4 跟踪 Job       → GET /v1/jobs · GET /v1/jobs/{id} · DELETE /v1/jobs/{id}
5 取出产物       → GET /v1/jobs/{id}/artifact[s]/{index}
```

每个步骤都显示它调用了哪些端点、真实路径、以及**可复制的 curl**。底部请求日志记录每一次调用，默认对 token 与 `X-Modal-2D-Session` 脱敏，勾选"显示密钥"后展示明文。

第 1 步提供**一键填入**：把 `modal token set --token-id … --token-secret …` 整条命令粘贴到输入框（或直接回车），自动拆出 id 与密钥并填入连接表单，省去手动拆分。凭据仍只进入进程内存，不回写命令到日志。

操作台在浏览器里独立校验端到端完整性：把响应头 `X-Artifact-SHA256` 与 Artifact descriptor 的 `sha256` 比对，一致才标记产物可信。

### 界面约束

- 纯静态资源（`modal_2d_client/ui/`），无构建步骤、无前端依赖，随包分发。
- 视觉语言对齐 `modal-3D/site`：Catppuccin Frappé 配色 + 编辑式排版（eyebrow + 大标题 + 指标卡片）。信息架构仍是任务导向的 5 步流程，装饰只服务于层级。
- 若配置了 `MODAL_2D_AGENT_TOKEN`，操作台会提示输入会话令牌；它只存在 `sessionStorage`，不回传后端。UI 静态资源放行免鉴权（浏览器导航无法携带自定义头），其发出的 XHR 仍受保护。
- 不引入 `/docs`、`/redoc`；端点清单由前端的 `ENDPOINTS` 常量维护，与 `app.py` 路由一一对应。新增路由时需同步该常量。

### 渲染核查

改动 UI 后应实际跑一遍，而不是只看编译通过：

```bash
uv run python -m tests.dev_stub      # 带假后端，不触网（可验证 409 分支）
node tests/audit.cjs                 # 正常流 + 布局审查（自动读 ~/.modal.toml 连真实 Modal）
node tests/audit_states.cjs          # 空态/离线/超长内容等边界
node tests/shots.cjs                 # 生成全流程截图
```

`audit.cjs` 会用真实凭据提交 Job 并等 GPU 出图，故较慢；只想查布局可用 `tests.dev_stub` 后端（此时 `audit_states.cjs` 的 409 分支才会真正走到）。

`tests/dev_stub.py` 与 `tests/fake_provider.py` 仅用于本地核查，不参与 pytest。

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

`modal-gen-client` 不吸收本仓的 Provider-specific Job/Artifact implementation；它只通过本地 API 做安全 transport。这样本 package 可以继续脱离 AgentScape 独立 smoke 和恢复测试。


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
