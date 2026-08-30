# modal-gen-client

`modal-gen-client` 是 `modal-provider` 的本地 Provider Hub。

它不实现 2D / 3D / EmbodiedGen / World 的业务，只负责把已安装 Provider 统一暴露给 AgentScape。

```text
AgentScape
    │ /connector/v1/*
    ▼
modal-gen-client
    ├── modal-2D-client
    ├── modal-3D-client
    ├── EmbodiedGen      (next)
    └── World / ...      (future)
```

## 边界

`modal-gen-client` 只拥有：

- Session / Pairing / Scope
- Provider Registry
- Capability Snapshot
- Global Job identity / idempotency
- Global Artifact identity / integrity
- Cross-provider Artifact routing

Provider 自己拥有：

- Modal SDK / credentials
- 模型、参数、conditioning、workflow
- Provider-private Job
- Provider-private Artifact
- retry / cancel / recovery

核心原则：**Provider 自治，gen-client 无知。**

## Provider 加载

2D / 3D 作为 Python package 直接加载，不经过 localhost HTTP：

```text
modal-gen-client
    │ Python entry point
    ├── modal_2d_client.provider:create_provider
    └── modal_3d_client.provider:create_provider
```

entry-point group：

```text
modal_gen.providers
```

新增 Provider 只需要实现统一 facade 并注册 entry point；gen-client 核心无需增加 Provider-specific module。

## Provider SPI

Provider facade 保持极小：

```text
descriptor()
submit(...)
get(job_id)
cancel(job_id)
iter_artifact(job_id, artifact_id)
```

统一 Job 只投影：

```text
global_job_id
provider
provider_job_id
operation
status
artifacts[]
```

统一 Artifact：

```text
global_artifact_id
provider_artifact_id
role
mime
bytes
sha256
```

`artifacts[]` 原生支持同一 Job 多个同 role 产物，可直接覆盖 2D batch、EmbodiedGen bundle 和未来 World 多产物。

## 当前 Provider

```text
modal-2d
  operation: modal-2d.image.text_to_image.v1
  output:    primary-image / image/png

modal-3d
  operation: modal-3d.asset.image_to_3d.v1
  input:     Connector sourceArtifact
  output:    primary-glb / model/gltf-binary
```

跨 Provider：

```text
2D
 ↓ PNG
Connector Artifact Registry
 ↓ verified local artifact
3D
 ↓ GLB
Connector Artifact Registry
```

Provider 私有 ID、Modal FunctionCall ID、Volume path 不跨边界泄漏。

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

默认只监听 loopback；Session 绑定 client identity、origin、scope、expiry 与 capability hash/revision。

## 开发

```bash
uv sync --dev
uv run ruff check modal_gen tests
uv run pytest -q
```

当前 2D / 3D 已通过 package entry point 直接接入。下一步按同一 SPI 接入 EmbodiedGen。

## Runtime topology

`modal-2D` / `modal-3D` 定义远程 GPU Runtime；`modal-2D-client` / `modal-3D-client` 是本地 Provider 控制库；`modal-gen-client` 负责统一调用、Runtime readiness 与部署生命周期。

```text
AgentScape / Browser
        ↓
modal-gen-client
    ├── modal-2D-client ──direct──> Modal 2D GPU workers
    ├── modal-3D-client ──direct──> Modal 3D GPU workers
    └── DeploymentService ────────> app.deploy()
```

2D / 3D 生成都由本地 client 直接 `Cls.from_name(...).spawn()` 到 GPU Worker，不经过远程 CPU gateway。2D capability 在本地读取 Runtime contract，PNG 通过 `Volume.read_file()` 直接读取；`modal-2d-prefetch` 仅是可选模型预取 utility，不参与正常生成链。

Provider 自己提供 deployment manifest，gen-client 不硬编码具体模型 Runtime。部署状态区分 `current / stale / missing / error / failed`，默认可以只部署缺失 Runtime；部署通过后台 Deployment Job 执行，全局最多并发 2 个 Runtime。Modal credentials 只保存在当前进程内存，不写入 Connector DB。

## Local UI

> 默认监听 `0.0.0.0`，方便 Docker / CNB / Codespaces 端口转发；默认允许任意浏览器 Origin。控制 token 未配置时仍为 `wangran`。生产环境建议显式设置 `MODAL_GEN_AGENT_TOKEN`，并可用 `MODAL_GEN_ALLOW_ANY_ORIGIN=0` 收紧 Origin。

推荐单命令启动 Connector 与可视化控制台，两者自动使用同一个本地控制 token：

```bash
# 本机默认 token 为 wangran；也可以显式覆盖：
# export MODAL_GEN_AGENT_TOKEN='<local-control-token>'
uv run modal-gen
```

仍保留独立调试入口：`uv run modal-gen-agent` 与 `uv run modal-gen-ui`。

打开：

```text
http://127.0.0.1:48124/
# /ui 和 /ui/ 仍兼容
```

控制台当前提供：

- Provider Hub 拓扑与 2D / 3D 连接状态
- 内存态 Modal credentials 连接 / 断开
- 实时 Capability / Model 展示
- Runtime `current / stale / missing` 检测、缺失部署与单 Runtime 更新
- 后台 Deployment Job 与最多 2 个 Runtime 并发部署
- 2D 文本生成图片
- 从 Connector PNG Artifact 继续提交 3D
- Job 状态轮询、取消与详情
- PNG 预览、GLB Artifact 与 SHA-256 校验下载

离线 UI 审查：

```bash
MODAL_GEN_UI_DEMO=1 modal-gen-ui
```

网络默认值：

```text
MODAL_GEN_HOST=0.0.0.0
MODAL_GEN_PORT=48123
MODAL_GEN_UI_HOST=0.0.0.0
MODAL_GEN_UI_PORT=48124
MODAL_GEN_ALLOW_ANY_ORIGIN=1   # 默认行为；设置 0 可关闭
```
