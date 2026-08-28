# modal-3D-client

`modal-3D-client` 是 `modal-3D` 的 **Reference Sidecar**。它不拥有 Project、Preprocess、UI、Asset 或 World；只把远端 3D Provider execution 映射成本地可恢复 Job，并负责输入上传与 GLB Artifact 校验/缓存。

```text
Caller / modal-inference-hub / Agent
          │ PNG / JPEG / WebP
          ▼
┌──────────────── modal-3D-client ────────────────┐
│ Local API                                       │
│   │                                             │
│   ├─ Capability / Model cache                   │
│   ├─ Source image upload → modal-3d-artifacts   │
│   ├─ Durable Job mirror / idempotent rebind     │
│   └─ GLB Volume fetch / verify / SHA cache      │
└──────────────────────┬───────────────────────────┘
                       ▼
                    modal-3D
                       │
                       ▼
                   GLB Artifact
```

## API

```text
GET    /health
GET    /modal/status
POST   /modal/connect
DELETE /modal/connect
GET    /v1/capabilities
GET    /v1/models
GET    /v1/jobs
POST   /v1/jobs                 multipart source image
GET    /v1/jobs/{id}
DELETE /v1/jobs/{id}
GET    /v1/jobs/{id}/artifact
```

`POST /v1/jobs` 接受 `PNG / JPEG / WebP` 原图。模型在请求进入时已经确定，因此 Sidecar 会立即异步 `spawn Model.warmup()`，让目标 L40S 在输入处理期间并行冷启动。可信 alpha/caller mask 直接在本地做 conditioning；普通 opaque 图片会由 Sidecar 直接调用 T4 `RemBgWorker.process` 获取 mask，同时目标 L40S 已在加载。mask 返回后，crop/refine/letterbox/canonicalization 仍全部在本地完成，再上传 1024×1024 RGBA 到 `client-inputs/` 并提交 `Model.generate_job`。不存在 Modal Gateway/CPU 转发层。

同一个 `job_id + source sha256 + model/profile/seed` 是稳定的本地 request identity。任务状态和 `FunctionCall.object_id` 持久化在本地 SQLite；客户端通过 `FunctionCall.from_id()` 轮询/取消。不存在 `modal-3d-gateway` 或远端 job-key registry。

## 本地验证

```bash
uv run --group dev ruff check .
uv run --group dev pytest -q
```

## Web UI

Sidecar 内置了一个 Task-oriented 产品界面，作为每个 curl 接口的可视化反馈。它不替代 API——每一个操作都精确对应上面的某个端点，用于把"步骤与业务逻辑"落到屏幕上。

**启动（演示模式，无需 Modal 账号或部署）**

```bash
MODAL_3D_CLIENT_DEMO=1 uv run python -m modal_3d_client
```

然后打开 http://127.0.0.1:3213/ui/ 。

演示模式（`MODAL_3D_CLIENT_DEMO=1`）返回一份假的 capability 文档并用内存 Job 模拟完整生命周期，方便离线走通「上传 → 提交 → 轮询 → 下载 GLB」。连接真实 Modal 时去掉该环境变量即可。

**界面结构（按用户流程组织）**

| 页面 | Primary Job | 对应接口 |
| --- | --- | --- |
| 工作台 | 上传图片并提交生成 | `GET /v1/models` → `POST /v1/jobs` |
| 任务 | 监控/取消/下载任务 | `GET /v1/jobs`、`GET|DELETE /v1/jobs/{id}`、`GET /v1/jobs/{id}/artifact` |
| 模型 | 查看可用模型与 profile | `GET /v1/models`、`GET /v1/capabilities` |
| 连接 | 连接/断开 Modal 与健康状态 | `GET /health`、`GET /modal/status`、`POST|DELETE /modal/connect` |
| API 参考 | 浏览每个可 curl 端点 | 全部 |

**本地会话令牌**

当设置了 `MODAL_3D_CLIENT_TOKEN` 时，API 请求需携带 `X-Modal-3D-Session` 头；界面会在「连接」页提供令牌输入（保存到浏览器 localStorage）。UI 静态资源与 `/ui/config` 不受该校验拦截，保证页面始终可加载并提示。

**监听地址与跨域**

服务默认监听 `0.0.0.0`，以便从容器网络 / 公网代理访问；CORS 默认允许任意来源（`Access-Control-Allow-Origin: *`）。

```bash
MODAL_3D_CLIENT_HOST=127.0.0.1   # 收窄回仅本机
MODAL_3D_CLIENT_ORIGIN=https://x.test  # 指定单一可信来源（其他来源仍返回 *）
MODAL_3D_CLIENT_PORT=3212               # 改端口
```

由于默认对外不设鉴权，公网暴露时建议至少设置 `MODAL_3D_CLIENT_TOKEN`。

**Render → Critique → Fix 审查**

`scripts/ui-review.mjs` 是截图 + 结构化审查的可复现入口（dev-only）：

```bash
npm install                 # 仅安装 playwright（dev 依赖）
# 另开一个 shell 跑演示服务，然后：
node scripts/ui-review.mjs
```

它会截图每个页面并输出 `findings.json`（溢出、控制台错误、完整流程）。
