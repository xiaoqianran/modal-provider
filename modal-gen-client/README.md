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
