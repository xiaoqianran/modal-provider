# modal-2D

`modal-2D` 是一个刻意保持很小的 Modal 文生图 Provider。当前只支持 **SANA-Sprint 0.6B / 1.6B**，输出固定为 1024×1024 lossless PNG。

```text
submit(request)
   │
   ├─ 校验稳定 generation contract
   ├─ CPU prefetch（已有完整 snapshot 就跳过）
   │
   ▼
SanaSprintWorker(model_id)
   │
   ├─ GPU: L40S
   ├─ 本地 Volume 权重，禁止推理容器临时下载
   │
   ▼
primary-image PNG
   │
   ├─ mediaType + bytes + sha256 digest
   ├─ producer identity
   ├─ opaque artifact id
   └─ Provider-private Volume location
```

## 设计边界

- 云端只负责模型、推理和远端 Artifact。
- Artifact 内容身份使用 `mediaType + bytes + sha256 digest`；`remote_path`/Modal Volume 仅是 Provider 私有位置，不进入 AgentScape 领域语义。
- `read_artifact` 暂保留为兼容 fallback；Reference Sidecar 优先直接读取命名 Volume，避免大 bytes 再经过一次 Modal Function result。
- 不包含 Web UI、SQLite、用户账号、Connector、业务编排。
- `submit` 是稳定异步边界，客户端可直接对 Modal FunctionCall 做 poll/cancel。
- 新模型通过 `ModelSpec` + 推理 adapter 扩展，不把模型分支散落到 HTTP/Job 层。

## 模型

- `sana-sprint-0.6b` → `Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers`
- `sana-sprint-1.6b` → `Efficient-Large-Model/Sana_Sprint_1.6B_1024px_diffusers`

默认：1.6B、固定 2 steps、guidance 4.5、seed 42。SANA-Sprint 的 SCM 路径不暴露可变 steps。

## 开发

```bash
uv sync --dev
uv run pytest -q
uv run modal deploy -m modal_2d.app
```

`modal-sana` 仅作为已验证的 SANA-Sprint / diffusers / L40S 运行参考；本仓没有继承它的 Web、ledger、batch、SQLModel 等应用层复杂度。
