# GitHub Pages benchmark

The public gallery compares four deployed `modal-3D` workers on a data-driven set of real images. The original 2026-08-23 gallery remains the baseline for the boat and coffee-cup scenes. The Pinterest Building scene was fully regenerated on 2026-08-24 after the production-quality texture/export fixes and the SAM 3.1 3D-mask repair were validated on Modal L40S.

## Input policy

The original scene is shown in the UI. Each benchmark scene records the actual preprocessing path used to materialize one content-addressed 1024×1024 canonical RGBA. Historical boat/building/cup scenes use SAM 3.1; the 2026-08-28 Teapot refresh uses BiRefNet. Every downstream model for a scene consumes the exact same canonical PNG.

For the SAM 3.1 image-to-3D path, a semantic mask can be non-empty yet still be a bad 3D contract. The production materializer detects multiple major connected fragments and may apply a bounded morphological repair. It searches for the smallest closing footprint that reduces fragmentation, rejects repairs that add more than 12% foreground area, does not merge far-separated objects, preserves the original `mask.png`, and writes the repaired `mask_3d.png` separately.

| Input | Selected subject |
| --- | --- |
| sample.webp | boat |
| Pinterest A1 | building |
| Pinterest 01 | cup |

This prevents each 3D worker from receiving a different background-removal result. The benchmark therefore compares the 3D models rather than separate preprocessing pipelines.

## Models

- FastSAM3D++ — default: embedded base-color textured GLB; `fast`: vertex-color GLB
- Hunyuan2.1++ — base shape sampling + Hunyuan3D Paint PBR
- Hermite-TRELLIS2++ — 1536 cascade + official remesh/to_glb PBR export
- Pixal3D — 1536 cascade + PBR export

All runs use seed 42 and NVIDIA L40S workers.

## 2026-08-24 Building refresh

The original Building SAM mask contained three major disconnected foreground regions. The repaired mask reduces those three major components to one with an 11.69% foreground-area increase, below the 12% safety budget. All four workers consumed the exact same repaired canonical RGBA.

The machine-readable evidence is stored in:

`benchmarks/pages-pinterest-a1-quality-2026-08-24.json`

That file records the canonical SHA256, mask-repair before/after statistics, complete Modal result payloads, artifact paths, and browser-preview SHA256 values.

## Full artifacts vs browser previews

The displayed inference time, face count, and `Full GLB` size belong to the **complete Modal artifact**. They are not recomputed from the web preview.

Pages assets are separate derivatives. Current Building previews preserve materials/vertex colors and use Draco geometry compression; textured outputs additionally use WebP texture compression. Every browser preview is capped at 15 MiB and is requested only after the user opens the 3D viewer.

## Deployment gate

`scripts/validate_pages.py` accepts any non-empty input set and requires exactly the four expected model IDs for every input. It verifies referenced files, declared preview byte counts, GLB v2 headers/lengths, path safety, and the 15 MiB per-preview budget before the Pages artifact can deploy.

## Safe refresh workflow

See `docs/BENCHMARKING.md`. New matrices are smoke-first, cost-budgeted, and dry-run by default. Canonical inputs are rejected before GPU submission when the visible foreground contains almost no RGB information.

## 2026-08-28 Teapot final refresh

The final post-hardening benchmark intentionally runs **one scene across the four models**, not a 5×4 matrix. The open-source TripoSR teapot is preprocessed with BiRefNet into one content-addressed 1024×1024 canonical RGBA and the exact same PNG is verified from Modal Volume before submission.

The machine-readable evidence is `benchmarks/pages-teapot-full-quality-2026-08-28.json`. Its FastSAM3D++ 6.16s record was produced by the former vertex-color shortcut and now belongs to `fast`; it is not a benchmark for the restored textured `recommended` profile. The historical Hunyuan2.1++ / Hermite-TRELLIS2++ / Pixal3D times remain 84.29s / 364.12s / 194.75s respectively.

The public gallery now displays each scene's actual preprocessing method instead of labeling every input as SAM 3.1. Teapot browser previews are separate Draco/WebP derivatives and do not change the full artifact metrics.

## 2026-09-21 FastSAM3D full-texture verification

The restored `recommended` FastSAM3D++ path is separately verified by `benchmarks/fastsam3d-full-textured-2026-09-21.json`. The smoke produced an embedded-base-color textured GLB with no vertex-color fallback. This verification does not rewrite the older public gallery records; those remain immutable historical `fast`-profile results.
