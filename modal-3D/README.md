# modal-3D

Minimal, decoupled Modal deployment layer for image-to-3D inference, plus a SAM 3.1 multi-object preprocessing service.

**Live benchmark:** https://xiaoqianran.github.io/modal-3D/

Current workers:

- FastSAM3D++
- Hunyuan2.1++
- Hermite-TRELLIS2++
- Pixal3D

Shared preprocessing:

- SAM 3.1 concept segmentation and native positive/negative box refinement
- selected instance materialization to canonical RGBA

## Design

`HTTP/Python client -> CPU gateway -> Modal spawn queue -> model-specific GPU worker -> persisted result`

Each GPU model has its own image and weight volume. Weights are downloaded without reserving a GPU and are loaded from mounted Volumes only when a GPU container starts.

Workers own their capability manifests and register them in `modal-3d-model-registry`. The Gateway reads that registry dynamically, so adding a model does not change `common.py`, `capabilities.py`, or `gateway.py`. Deploy and register a worker with one command:

```powershell
./scripts/deploy-worker.ps1 modal_3d/fastsam3d_plus_plus.py
```

Run the script once for every existing worker before the first registry-backed Gateway deployment. Then deploy the HTTP gateway with `modal deploy modal_3d/gateway.py`. It exposes `/capabilities`, `/tasks`, `/pipelines`, `/tasks/{task_id}`, and `/artifacts/{path}`. The raw-image pipeline overlaps explicit model warmup with SAM 3.1 segmentation; direct canonical-RGBA jobs do not enqueue a redundant warmup call.

SAM 3.1 is deployed as a separate preprocessing service rather than being embedded into the 3D workers. The live gallery now shows four active workers. Historical 3×5 benchmark evidence, including the retired trellis.cpp run, is preserved under `benchmarks/`.

See `docs/PLAN.md`, `docs/SAM3_1_PREPROCESSOR.md`, and `docs/PAGES_BENCHMARK.md` for architecture and benchmark details.

## Status

Four L40S image-to-3D workers and the SAM 3.1 preprocessor are deployed and benchmarked. GitHub Pages is published through `.github/workflows/pages.yml`; full-output metrics and separately optimized browser previews are kept distinct.
