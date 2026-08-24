# GitHub Pages benchmark

The public gallery compares four deployed `modal-3D` workers on three real images. The original 2026-08-23 gallery remains the baseline for the boat and coffee-cup scenes. The Pinterest Building scene was fully regenerated on 2026-08-24 after the production-quality texture/export fixes and the SAM 3.1 3D-mask repair were validated on Modal L40S.

## Input policy

The original scene is shown in the UI. Before any 3D worker runs, SAM 3.1 selects one object instance and materializes the same 1024×1024 canonical RGBA for every downstream model.

For image-to-3D, a semantic mask can be non-empty yet still be a bad 3D contract. The production materializer now detects multiple major connected fragments and may apply a bounded morphological repair. It searches for the smallest closing footprint that reduces fragmentation, rejects repairs that add more than 12% foreground area, does not merge far-separated objects, preserves the original `mask.png`, and writes the repaired `mask_3d.png` separately.

| Input | Selected subject |
| --- | --- |
| sample.webp | boat |
| Pinterest A1 | building |
| Pinterest 01 | cup |

This prevents each 3D worker from receiving a different background-removal result. The benchmark therefore compares the 3D models rather than separate preprocessing pipelines.

## Models

- FastSAM3D++ — vertex-color GLB
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

`scripts/validate_pages.py` validates exactly three inputs and exactly four model IDs per input. It verifies referenced files, declared preview byte counts, GLB v2 headers/lengths, path safety, and the 15 MiB per-preview budget before the Pages artifact can deploy.
