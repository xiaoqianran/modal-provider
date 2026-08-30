# modal-3D

Minimal Modal GPU workers for image-to-3D inference. The VPS/client owns
routing, job state and canonicalization; Modal is used only for useful GPU
compute.

## Required deployment Secret

Before deploying any worker, create a Secret named `huggingface` in the Modal
`main` environment with `HF_TOKEN` set to a Hugging Face token that can access
the target models. The deployment flow checks weights, downloads missing
weights, verifies them, and only then deploys the worker. A missing Secret or
failed download stops deployment.

**Live benchmark:** https://xiaoqianran.github.io/modal-3D/

Current 3D workers:

- FastSAM3D++
- Hunyuan2.1++
- Hermite-TRELLIS2++
- Pixal3D

Optional preprocessing worker:

- BiRefNet `RemBgWorker` on T4, used only for opaque sources without an existing
  alpha channel/caller mask.

## Production path

Two input paths share the same GPU workers:

```text
Direct modal-3D-client upload
PNG / JPEG / WebP
  -> local validation + target-worker warmup
  -> [opaque/no mask only] T4 RemBgWorker.process -> mask
  -> local refine + crop/letterbox -> canonical 1024x1024 RGBA
  -> modal-gen-artifacts/client-inputs/<sha256>.png
  -> selected L40S Model.generate_job
  -> GLB

modal-gen shared Artifact handoff
content-addressed source in modal-gen-artifacts/sources/sha256/...
  -> metadata-only handoff when the source already exists in Modal
  -> T4 RemBgWorker.prepare reads the shared source and canonicalizes in Modal
  -> modal-gen-artifacts/client-inputs/<sha256>.png
  -> selected L40S Model.generate_job
  -> GLB
```

There is no `modal-3d-gateway`, no Modal CPU dispatch function and no worker CPU
adapter. The shared Artifact path avoids downloading a 2D result to the client only
to upload the same bytes back to Modal. A source that already has meaningful alpha
can skip BiRefNet inference; an opaque source uses the T4 because that container does
real foreground-mask work.

The four L40S workers are `max_containers=1` and intentionally have no
`@modal.concurrent`; each warm model processes one generation at a time. The T4
worker is also conservatively `max_containers=1`.

The **internal model-worker input contract** is:

- PNG, 1024×1024, 8-bit RGBA;
- transparent letterbox padding;
- content-addressed path under `client-inputs/`;
- meaningful foreground alpha.

The public/source contract is broader: `PNG / JPEG / WebP` up to the configured
source-size limit. Opaque sources are canonicalized before they reach a model worker.

Each 3D worker exposes only the direct generation method:

```python
cls = modal.Cls.from_name("modal-3d-pixal3d", "Model")
call = cls().generate_job.spawn("client-inputs/<sha256>.png", options)
# persist call.object_id; restore with modal.FunctionCall.from_id(...)
```

The T4 worker exposes both the legacy byte/mask method and the shared-volume handoff:

```python
cls = modal.Cls.from_name("modal-3d-rembg", "RemBgWorker")
mask = cls().process.remote(source_bytes)
prepared = cls().prepare.remote("sources/sha256/ab/<sha256>")
```

Weights are prepared without reserving a GPU and loaded from mounted Volumes
when the corresponding GPU container starts. `deploy-worker.ps1` checks and
downloads the selected worker's weights first; a failed download aborts the
deployment. Deployments started through `modal-gen-client` use the same
check-download-verify gate.

Deploy modules directly; there is no registration step:

```powershell
./scripts/deploy-worker.ps1 modal_3d/rembg_worker.py
./scripts/deploy-worker.ps1 modal_3d/fastsam3d_plus_plus.py
./scripts/deploy-worker.ps1 modal_3d/hunyuan2_1_plus_plus.py
./scripts/deploy-worker.ps1 modal_3d/hermit_trellis2_plus_plus.py
./scripts/deploy-worker.ps1 modal_3d/pixal3d.py
```

## 验收记录

2026-08-31：本地正式测试目录 `77 passed`、`20 subtests`；本次修改文件 Ruff/format 全部通过。配置
`huggingface` Secret 后，FastSAM3D 空权重 Volume 自动下载、校验并部署，约 4～5 分钟。
真实 RGBA PNG → GLB 成功，GLB v2、1,520,464 bytes、37,990 vertices、75,968 faces，
L40S 推理约 5.8 秒，完整远端调用约 42 秒。

直接调用 `Model.generate_job` 时仍必须提供 canonical RGBA；通过 `modal-3D-client` 或 `modal-gen` 的 source contract 可以提交 PNG/JPEG/WebP，opaque 图片会先经过 conditioning。

Generation/task/artifact HTTP APIs live in the sibling `modal-3D-client` package, not in this
provider package. Historical benchmark evidence is preserved under
`benchmarks/`; retired experiments live under `archive/`.

See `docs/ARCHITECTURE.md` for the production boundaries.
