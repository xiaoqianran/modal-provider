# Hunyuan2.1-plus-plus / L40S

Current production profile is the full Hunyuan3D-2.1 asset path, not geometry-only:

- Shape: base/original sampler, 50 inference steps.
- Paint: Hunyuan3D-Paint 2.1 PBR, 6 views at 512 resolution.
- Paint remesh: **enabled** for the official full-quality baseline.
- Final paint export follows the upstream PBR path (4096 working texture, downsampled export near 2048).
- L40S only, `min_containers=0`, `max_containers=1`.
- Model/fork revisions are pinned; GPU startup is offline.

The old ~29s reference measured the shape/geometry-era path and must not be presented as full textured performance. The latest valid full-pipeline record is `benchmarks/pages-pinterest-a1-quality-2026-08-24.json` (~557s with `paint_remesh=false`), so the current `remesh=true` profile is intentionally marked **stale until a valid smoke refreshes it**.

```bash
modal run -m modal_3d.hunyuan2_1_plus_plus::sync_weights
./scripts/deploy-worker.ps1 modal_3d/hunyuan2_1_plus_plus.py
```

## Full-quality acceleration A/B

The verified `recommended` profile remains unchanged: base sampler, 50 shape
steps, six-view 512 PBR paint and `paint_remesh=true`. Load-time accelerators
are opt-in environment switches so benchmark variants cannot silently change
request quality:

- `HUNYUAN_ENABLE_FLASHVDM=1`: enables only the pinned fork's FlashVDM VAE
  decoder path with `replace_vae=false`. It keeps the Hunyuan3D-2.1 VAE and
  the request's 50 denoising steps; this is not the separate 5-step turbo
  checkpoint claim.
- `HUNYUAN_ENABLE_COMPILE=1`: calls the pinned pipeline's `compile()` at load
  time. First-call compile cost must be kept separate from steady-state warm
  latency.
- `USE_SAGEATTN=1`: supported by the pinned denoiser at import time, but kept
  benchmark-gated until a pinned SM89 SageAttention artifact and same-seed
  geometry/PBR quality comparison exist.

Use the frozen station harness after deploying the instrumented worker:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_hunyuan.py --variant base-official --runs 2
.\.venv\Scripts\python.exe scripts\benchmark_hunyuan.py --variant flashvdm-decoder --runs 2
.\.venv\Scripts\python.exe scripts\benchmark_hunyuan.py --variant compile-official --runs 2
.\.venv\Scripts\python.exe scripts\benchmark_hunyuan.py --variant flashvdm-compile --runs 2
```

Every record keeps shape and paint latency separate and includes the active
runtime-acceleration flags. The PBR GLB quality guard still runs before the
artifact is committed.

## Historical geometry benchmark notes
