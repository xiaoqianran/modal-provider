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

## Historical geometry benchmark notes
