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
   ├─ SHA-256
   ├─ bytes
   └─ opaque artifact id
```

## 设计边界

- 云端只负责模型、推理和远端 Artifact。
- 不包含 Web UI、SQLite、用户账号、Connector、业务编排。
- `submit` 是稳定异步边界，客户端可直接对 Modal FunctionCall 做 poll/cancel。
- 新模型通过 `ModelSpec` + 推理 adapter 扩展，不把模型分支散落到 HTTP/Job 层。

## 模型

- `sana-sprint-0.6b` → `Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers`
- `sana-sprint-1.6b` → `Efficient-Large-Model/Sana_Sprint_1.6B_1024px_diffusers`

默认：1.6B、2 steps、guidance 4.5、seed 42。steps 仅允许 1–4。

## 开发

```bash
uv sync --dev
uv run pytest -q
uv run modal deploy modal_2d/app.py
```

`modal-sana` 仅作为已验证的 SANA-Sprint / diffusers / L40S 运行参考；本仓没有继承它的 Web、ledger、batch、SQLModel 等应用层复杂度。
