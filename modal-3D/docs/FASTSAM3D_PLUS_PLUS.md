# FastSAM3D-plus-plus / L40S

Production single-object **textured asset** worker for `Archerkattri/fastsam3d-plus-plus`, pinned at `36191e4`.

The default `recommended` profile is the full asset path: Fast-SAM3D++ generation followed by mesh postprocess, texture baking and layout postprocess. The former provider shortcut is preserved only as the explicit `fast` profile and exports a vertex-color GLB.

Submissions are spawned directly on `Model.generate_job`. It reads the uploaded canonical input, validates it, runs inference, validates the resulting GLB against the selected appearance contract, and returns the normalized generation-result contract inside the GPU container.

- GPU: L40S / `sm_89`
- CUDA: 12.1.1
- PyTorch: 2.5.1+cu121
- sparse backend: spconv 2.3.8
- attention backend: PyTorch SDPA
- native bundle: `fastsam3d-native-py311-cu121-torch251-sm89-v3`
- PyTorch3D: pinned prebuilt wheel
- Gaussian texture-observation renderer: pinned `gsplat` wheel
- mesh/raster postprocess: pinned `nvdiffrast` wheel
- texture optimizer: PyTorch3D
- input: pre-matted RGBA
- default output: embedded base-color textured GLB
- `fast` output: vertex-color GLB
- one resident GPU model, `max_containers=1`
- no runtime model compilation

## Profiles

### `recommended`

```text
Fast-SAM3D++ SS generation
→ SLaT generation
→ mesh + Gaussian decode
→ mesh postprocess
→ multi-view texture observation
→ UV parameterization / optimized texture baking
→ layout postprocess
→ textured GLB
```

Runtime flags are equivalent to:

```python
with_mesh_postprocess=True
with_texture_baking=True
with_layout_postprocess=True
use_vertex_color=False
```

The runtime image therefore keeps the postprocess dependencies that the old provider patch removed: `xatlas`, `pyvista`, `pymeshfix`, `igraph`, `open3d`, plus pinned `gsplat` and `nvdiffrast` native wheels. The `slat_decoder_gs_4` config and checkpoint also remain enabled in the derived pipeline configuration.

The restored path is **verified** by `benchmarks/fastsam3d-full-textured-2026-09-21.json`. On Modal L40S, the biplane smoke produced a 1,842,756-byte GLB with embedded base-color texture, no vertex-color fallback, `mesh_postprocess=true`, `texture_baking=true`, and `layout_postprocess=true`. Worker inference was 35.71 s, worker job total was 37.27 s, startup was 32.30 s, and peak allocated VRAM was about 17.02 GiB.

### `fast`

The old provider behavior remains available explicitly:

```python
with_mesh_postprocess=False
with_texture_baking=False
with_layout_postprocess=False
use_vertex_color=True
```

This profile is useful when latency matters more than full asset finishing, but it is no longer the default and must not be described as equivalent to the full textured pipeline.

## Generator acceleration

Both profiles keep Fast-SAM3D's native acceleration path: `ShortCut_faster` for sparse-structure generation, token carving in the SLaT stage, and the HFER mesh policy. HiCache++ DMD remains available but defaults to off (`dmd_interval=1`). These acceleration mechanisms are separate from the asset-finishing profile.

The underlying generator YAMLs declare SS `2` / SLaT `12`, while the deployed pipeline overrides runtime `inference_steps` to 25 / 25. No runtime step count was reduced as part of the full-path restoration.

## Historical benchmark note

The earlier L40S warm measurements (roughly 2.6–6 seconds worker inference depending on warm-up) and the 2026-08-28 / 2026-09-08 records were produced by the vertex-color shortcut. They now belong to the `fast` profile only. They must not be used as the latency or quality baseline for `recommended`.

## Deploy

```bash
modal run -m modal_3d.fastsam3d_plus_plus::sync_weights
./scripts/deploy-worker.ps1 modal_3d/fastsam3d_plus_plus.py
```
