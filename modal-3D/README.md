# modal-3D

Minimal Modal GPU workers for image-to-3D inference. The VPS/client owns
routing, job state and canonicalization; Modal is used only for useful GPU
compute.

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

```text
source
  -> local validation
  -> [opaque/no mask only] direct T4 RemBgWorker.process -> mask
  -> local mask refine + crop/letterbox + canonical 1024x1024 RGBA PNG
  -> upload client-inputs/<sha256>.png
  -> direct selected L40S Model.generate_job
  -> GLB
```

There is no `modal-3d-gateway`, no Modal CPU dispatch function and no worker CPU
adapter. An already-matted source goes straight from the VPS to the selected
L40S worker. An opaque source pays for the T4 only because that container does
real mask inference.

The four L40S workers are `max_containers=1` and intentionally have no
`@modal.concurrent`; each warm model processes one generation at a time. The T4
mask worker is also conservatively `max_containers=1` with no input-concurrency
decorator until concurrent ONNX inference is separately benchmarked.

The 3D input contract is:

- PNG, 1024×1024, 8-bit RGBA;
- transparent letterbox padding;
- content-addressed path under `client-inputs/`;
- meaningful foreground alpha.

Each 3D worker exposes only the direct generation method:

```python
cls = modal.Cls.from_name("modal-3d-pixal3d", "Model")
call = cls().generate_job.spawn("client-inputs/<sha256>.png", options)
# persist call.object_id; restore with modal.FunctionCall.from_id(...)
```

The T4 mask worker is also called as a class method, not through a gateway:

```python
cls = modal.Cls.from_name("modal-3d-rembg", "RemBgWorker")
mask = cls().process.remote(source_bytes)
```

Weights are prepared without reserving a GPU and loaded from mounted Volumes
when the corresponding GPU container starts.

Deploy modules directly; there is no registration step:

```powershell
./scripts/deploy-worker.ps1 modal_3d/rembg_worker.py
./scripts/deploy-worker.ps1 modal_3d/fastsam3d_plus_plus.py
./scripts/deploy-worker.ps1 modal_3d/hunyuan2_1_plus_plus.py
./scripts/deploy-worker.ps1 modal_3d/hermit_trellis2_plus_plus.py
./scripts/deploy-worker.ps1 modal_3d/pixal3d.py
```

Generation/task/artifact HTTP APIs live in the sibling `modal-3D-client` package, not in this
provider package. Historical benchmark evidence is preserved under
`benchmarks/`; retired experiments live under `archive/`.

See `docs/ARCHITECTURE.md` for the production boundaries.
