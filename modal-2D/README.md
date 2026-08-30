# modal-2D

`modal-2D` 是一个刻意保持很小的 Modal 文生图 Provider。当前只支持 **SANA-Sprint 0.6B / 1.6B**，输出固定为 1024×1024 lossless PNG。

```text
本地 client（modal-2D-client）
   │
   ├─ 本地校验 public request + capability
   └─ 按 model 直接 Cls.from_name("modal-2d", "SanaSprintWorker")(model_id=...)
        │
        ▼
SanaSprintWorker(model_id)          ← 生成热路径唯一入口，没有 CPU 中转 Function
   │
   ├─ normalize_request / normalize_batch_request（服务端最后一道校验）
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
- `SanaSprintWorker.generate` / `.generate_batch` 是稳定异步边界，客户端直接对 GPU Worker 的 Modal FunctionCall 做 poll/cancel。生成热路径上没有 `submit` 这类 CPU 中转 Function：Modal 每多一层 Function 就多一次独立冷启动，中转层只会让首次请求先等一次 CPU 容器、再等一次 GPU 容器。
- Worker 自己完成最后一道服务端校验：客户端只传 public payload（`prompt` / `model` / `seed` | `seeds` / `guidance`），`steps`、`width`、`height`、`output` 由服务端 normalize 产生，不接受外部传入。
- `generate_batch` 把同 prompt 的多个 seed 放进同一个 `SanaSprintWorker`；一个 GPU/pipeline 顺序生成全部候选，避免 Modal 因并发 candidate 产生 cold-start overscaling。
- `prefetch` 是显式模型准备 capability，不进入每次 generation hot path。
- SANA-Sprint 权重是公开模型，`prefetch` 默认不要求 Hugging Face secret；如需要认证下载，可在部署时设置 `MODAL_2D_HF_SECRET=huggingface`（该 secret 提供 `HF_TOKEN`）。
- 每个参数化模型 worker variant 都受 `max_containers=1` 限制，防止并发请求横向拉起多张 L40S；当前没有启用 `@modal.concurrent`，单个同步 Diffusers pipeline 保持串行处理。
- Worker `scaledown_window=300s`，让短时间连续生成复用已加载 pipeline。
- 新模型通过 `ModelSpec` + 推理 adapter 扩展，不把模型分支散落到 HTTP/Job 层。

## 模型

- `sana-sprint-0.6b` → `Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers`
- `sana-sprint-1.6b` → `Efficient-Large-Model/Sana_Sprint_1.6B_1024px_diffusers`

默认：1.6B、固定 2 steps、guidance 4.5、seed 42。SANA-Sprint 的 SCM 路径不暴露可变 steps。

## 开发

```bash
uv sync --dev
uv run pytest -q
./scripts/deploy-all.sh
```

`deploy-all.sh` 会先逐个检查并预取模型权重；任一下载失败时立即终止，不会继续部署
worker。通过 `modal-gen-client` 发起部署时也执行同样的检查、下载和二次校验。公开的
SANA-Sprint 不强制要求 Token；统一部署其他需要授权的 Hugging Face 模型时，必须先配置
Modal `main` 环境中的 `huggingface` Secret，并提供 `HF_TOKEN`。

## 验收记录

2026-08-31：本地 `30 passed`，约 9 秒；Ruff 全部通过。真实 Modal 空权重 Volume
自动下载并校验后部署 SANA Worker，约 2 分 45 秒；随后真实 prompt 生成
`1024×1024 image/png`，约 10 秒。

`modal-sana` 仅作为已验证的 SANA-Sprint / diffusers / L40S 运行参考；本仓没有继承它的 Web、ledger、SQLModel 或 batch scheduler。这里的 batch 只是一个深 Provider capability：同一 worker 对多个 seed 顺序推理。


## Verified Batch Baseline

2026-08-28，`sana-sprint-1.6b` 在 L40S 上用 `seeds=[42,73,104,135]` 做连续 cold → warm 实测：

```text
old: 4 independent GPU jobs    ~54.2 s
cold: one batch job             43.362 s
warm: one batch job              9.075 s
warm provider batch compute      6.782 s
```

Warm worker 内真实单图 inference：

```text
seed 42    1.352 s
seed 73    1.353 s
seed 104   1.240 s
seed 135   2.428 s
```

Warm batch 返回 `worker_reused=true`、`worker_load_ms=null`；cold batch 单独记录本次 `worker_load_ms`。这样外层 Job wait 不再被误解为模型推理时间。

## Unified benchmark harness

`scripts/benchmark.py` benchmarks the deployed production workers through the same capability-driven route used by clients. It does not duplicate model loading or inference code.

Default run benchmarks every advertised model with warm batch sizes `1,2,4,8`:

```bash
uv run python scripts/benchmark.py --output benchmark-results/all.json
```

Select one or more models when a full run would be too expensive:

```bash
uv run python scripts/benchmark.py \
  --model sana-sprint-1.6b \
  --model z-image-turbo \
  --batches 1,2,4,8 \
  --output benchmark-results/fast-models.json
```

Each model gets one initial batch-1 cold probe followed by the requested warm runs. `coldStartObserved` is only `true` when the Worker itself reports a real model load; an already-warm container is never reported as a cold start.

The report includes:

- end-to-end latency and latency per image;
- Worker model-load and batch timing;
- per-image inference timing;
- CUDA GPU name and peak allocated/reserved VRAM;
- artifact count and byte sizes;
- GPU-seconds consumed by the observed load/inference window;
- optional cost estimates when an explicit current GPU hourly rate is supplied.

GPU prices are deliberately not hard-coded. Supply them at run time if cost estimates are needed:

```bash
uv run python scripts/benchmark.py \
  --model qwen-image-2512 \
  --gpu-rate 'RTX-PRO-6000=YOUR_CURRENT_USD_PER_HOUR' \
  --output benchmark-results/qwen.json
```

`benchmark-results/` is intended as ephemeral output; keep benchmark reports outside commits unless a specific result is being documented as an experiment.
