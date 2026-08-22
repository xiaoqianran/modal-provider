# Hunyuan2.1-plus-plus / L40S

Production geometry worker for `Archerkattri/hunyuan2.1-plus-plus`, pinned at `9efd760`.

- L40S only, CUDA 12.4.1, PyTorch 2.5.1+cu124
- geometry only; no Hunyuan paint stack
- CPU-only weight sync downloads only `hunyuan3d-dit-v2-1/*` (~6.86 GiB), pinned to base-model revision `0b94677654c57bb9a6b6845cd7b704ccf551d327`
- GPU starts offline, loads once in `@modal.enter()`, one request at a time
- pre-matted RGBA input only
- no runtime compilation
- top-level `generate(input_path, options)` keeps the existing gateway contract; it only reads the shared artifacts Volume and delegates to the resident GPU class

The worker defaults to `interval=3, history=6`. On the L40S chair smoke, this gave a warm median of `26.32s` inference versus `29.90s` for the same fork at `interval=1` (full transformer every step): about `1.136x` speedup / `12.0%` less inference time.

`interval=5` was faster (~`24.34s`) but changed the geometry much more in the same sample, so it is intentionally not the production default. The interval sweep and topology notes live in `benchmarks/hunyuan2.1-plus-plus-l40s-2026-08-23.json`.

```bash
modal run modal_3d/hunyuan2_1_plus_plus.py::sync_weights
modal deploy modal_3d/hunyuan2_1_plus_plus.py
```
