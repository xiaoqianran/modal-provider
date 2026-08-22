# modal-3D

Minimal, decoupled Modal deployment layer for four accelerated image-to-3D pipelines:

- Archerkattri/hunyuan2.1-plus-plus
- Archerkattri/sam3d-plus-plus
- Archerkattri/fastsam3d-plus-plus
- Archerkattri/hermit-trellis2-plus-plus

## Design

`local app -> CPU gateway -> Modal spawn queue -> model-specific GPU worker -> persisted result`

The gateway is intentionally model-agnostic. Each GPU model has its own image and weight volume.
Weights are downloaded without reserving a GPU and are loaded from the mounted volume only when a GPU container starts.

See `docs/PLAN.md` for the benchmark/deployment plan.

## Status

Repository scaffold created. Upstream source review and runtime baselining are in progress; concrete model workers are added one at a time so build/runtime failures stay isolated.
