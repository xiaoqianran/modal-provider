# Pixal3D / L40S

Reference experiment: `xiaoqianran/modal-lab/005-v2-pixal3d-l40s`.

The production worker deliberately keeps only the proven environment and inference path:

- Python 3.10 / CUDA 12.4.1 / PyTorch 2.6.0 / SM89
- L40S only, `max_containers=1`, one request per container
- six native CUDA wheels come from `modal-build`; runtime never compiles
- model and auxiliary weights are synchronized on CPU to a Modal Volume
- GPU starts offline and loads the Pixal3D pipeline once in `@modal.enter()`
- official standard/full-quality mode: 1536 cascade, 49152 token budget, 4096 PBR texture export
- 1024 is retained only as the upstream low-VRAM alternative, not the production benchmark default
- L40S uses the resident-model path instead of the lab's per-request low-VRAM reload path

Lab-only build/verify/viewer/CLI code is intentionally not copied into production.

## Current benchmark reference

`benchmarks/pages-pinterest-a1-quality-2026-08-24.json` records the current 1536/4096 standard profile at ~197.18s worker inference on L40S. The older ~108.92s reference came from a 1024-era profile and is no longer used as the recommended-profile latency.
