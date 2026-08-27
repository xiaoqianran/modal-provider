# modal-3D-client

`modal-3D-client` 是 `modal-3D` 的 **Reference Sidecar**。它不拥有 Project、Preprocess、UI、Asset 或 World；只把远端 3D Provider execution 映射成本地可恢复 Job，并负责输入上传与 GLB Artifact 校验/缓存。

```text
Caller / modal-inference-hub
          │ canonical RGBA PNG
          ▼
┌──────────────── modal-3D-client ────────────────┐
│ Local API                                       │
│   │                                             │
│   ├─ Capability / Model cache                   │
│   ├─ Canonical upload → modal-3d-artifacts      │
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
POST   /v1/jobs                 multipart canonical PNG
GET    /v1/jobs/{id}
DELETE /v1/jobs/{id}
GET    /v1/jobs/{id}/artifact
```

`POST /v1/jobs` 只接受已经 canonicalized 的 `1024×1024 RGBA PNG`。原图处理、rembg、component selection 都属于上层 `modal-inference-hub`，不属于本仓。

同一个 `job_id + canonical sha256 + model/profile/seed` 是稳定 request identity。若 gateway submit 的网络结果未知，Client 会以同一个 content-addressed input path 重试；`modal-3D` gateway 的幂等 job key 会绑定回原 remote task。

## 本地验证

```bash
uv run --group dev ruff check .
uv run --group dev pytest -q
```
