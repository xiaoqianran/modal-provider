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

`POST /v1/jobs` 接受 `PNG / JPEG / WebP` 原图并按 SHA-256 原样上传。Sidecar 不做 resize、rembg、crop 或 canonicalization；模型必需的自动 Input Conditioning 由 `modal-3D` Provider 拥有。Caller 如果已有可信 alpha/mask，Provider 会优先保留；Human/Agent 对“选择哪个物体”的语义决策仍属于 Caller。

同一个 `job_id + source sha256 + model/profile/seed` 是稳定 request identity。若 gateway submit 的网络结果未知，Client 会以同一个 content-addressed input path 重试；`modal-3D` gateway 的幂等 job key 会绑定回原 remote task。

## 本地验证

```bash
uv run --group dev ruff check .
uv run --group dev pytest -q
```
