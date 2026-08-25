# modal-3D

Minimal, decoupled Modal deployment layer for image-to-3D inference. All 2D preprocessing lives in `modal-3D-client`; this repository only consumes canonical 1024×1024 RGBA PNG inputs from the shared Modal Volume.

**Live benchmark:** https://xiaoqianran.github.io/modal-3D/

Current workers:

- FastSAM3D++
- Hunyuan2.1++
- Hermite-TRELLIS2++
- Pixal3D

Input contract:

- PNG, 1024×1024, 8-bit RGBA
- object aspect ratio is preserved by the client
- transparent letterbox padding is produced locally by `modal-3D-client`
- cloud workers do not perform background removal, segmentation, cropping, or subject selection

## Design

`HTTP/Python client -> CPU gateway -> Modal spawn queue -> model-specific GPU worker -> persisted result`

Each GPU model has its own image and weight volume. Weights are downloaded without reserving a GPU and are loaded from mounted Volumes only when a GPU container starts.

Workers own their capability manifests and register them in `modal-3d-model-registry`. The Gateway reads that registry dynamically, so adding a model does not change `common.py`, `capabilities.py`, or `gateway.py`. Deploy and register a worker with one command:

```powershell
./scripts/deploy-worker.ps1 modal_3d/fastsam3d_plus_plus.py
```

Run the script once for every existing worker before the first registry-backed Gateway deployment. Then deploy the Gateway. The public HTTP surface is intentionally read-only and exposes only `/capabilities`; generation, task status, and artifact access use authenticated Modal Function calls from `modal-3D-client`.

The live gallery shows four active workers. The retired SAM 3.1 preprocessing implementation and its experiment notes are preserved under `archive/sam3_1/`; they are not part of the live generation path. Historical benchmark evidence is preserved under `benchmarks/`.

See `docs/PLAN.md` and `docs/PAGES_BENCHMARK.md` for architecture and benchmark details.

## Status

Four L40S image-to-3D workers are deployed and benchmarked. GitHub Pages is published through `.github/workflows/pages.yml`; full-output metrics and separately optimized browser previews are kept distinct.
