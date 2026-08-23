# GitHub Pages benchmark

The public gallery compares five deployed `modal-3D` workers on three real images. All 15 full outputs were regenerated on 2026-08-23 after the Modal workspace migration.

## Input policy

The original scene is shown in the UI. Before any 3D worker runs, SAM 3.1 selects one object instance and the selected mask is materialized to the same 1024×1024 canonical RGBA for every downstream model.

| Input | Selected subject |
| --- | --- |
| sample.webp | boat |
| Pinterest A1 | building |
| Pinterest 01 | cup |

This prevents each 3D worker from receiving a different background-removal result. The benchmark therefore compares the 3D models, not five preprocessing pipelines.

## Models

- FastSAM3D++
- Hunyuan2.1++
- Hermite-TRELLIS2++
- Pixal3D
- trellis.cpp

All runs use seed 42 and NVIDIA L40S workers.

## Full artifacts vs browser previews

The displayed inference time, vertex/face count, and `Full GLB` size belong to the **complete Modal artifact**. They are not recomputed from the web preview.

The Pages assets are separate derivatives. Geometry previews are simplified when necessary and Draco-compressed. Pixal3D keeps its UV/PBR material and uses quantized geometry with WebP texture compression. Every browser preview is capped at 15 MiB and is only requested after the user opens the 3D viewer.

The 15 browser previews total about 48 MiB, but the landing page does not download them eagerly.

## Evidence

Machine-readable provenance, preprocessing selections, full-output metrics, and preview sizes are recorded in:

`benchmarks/pages-l40s-2026-08-23.json`

The Pages Action rejects deployment if any of the three inputs is missing one of the five model IDs, an input/preview file does not exist, or a preview exceeds 15 MiB.
