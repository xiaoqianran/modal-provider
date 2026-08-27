# FastSAM3D-plus-plus / L40S

Production single-object geometry worker for `Archerkattri/fastsam3d-plus-plus`, pinned at `36191e4`.

Runtime policy: `min_containers=0`, `scaledown_window=120`. The capability reports warm wall time (`6.06s`) separately from the current production cold-start reference (`105s`).

- GPU: L40S / `sm_89`
- CUDA: 12.1.1
- PyTorch: 2.5.1+cu121
- sparse backend: spconv 2.3.8
- attention backend: PyTorch SDPA
- PyTorch3D: build-time compile, pinned commit
- input: pre-matted RGBA
- output: vertex-color GLB
- one resident GPU model, `max_containers=1`
- no runtime compilation

CPU-only `sync_weights()` pins Meta SAM 3D Objects and MoGe revisions, then deterministically generates Fast-SAM3D's two missing `*_faster.yaml` configs from the pinned baseline configs. The final weight Volume is about 12.76 GiB.

The worker keeps Fast-SAM3D's native acceleration path enabled: `ShortCut_faster` for sparse-structure generation, token carving in the slat stage, and the HFER mesh policy. HiCache++ DMD remains available but defaults to **off** (`dmd_interval=1`).

The deployed top-level `generate(input_path, options)` adapter was also validated with no DMD option supplied; it resolved to `dmd_interval=1 / dmd_enabled=false` and produced a valid GLB.

On the L40S chair smoke, a fair same-container warm comparison was:

```text
interval=1 (DMD off)  2.579s
interval=3            2.600s
interval=4            2.636s
interval=6            2.652s
```

The first control inference was 5.73s because it included first-inference warm-up effects; comparing that run with later DMD calls would falsely suggest a ~2x DMD speedup. The steady-state comparison shows no DMD benefit for this workload, so production does not enable it by default.

All tested outputs were watertight with zero boundary and non-manifold edges. DMD changed surface geometry slightly (~0.35–0.38% normalized symmetric surface distance versus control) without reducing warm latency.

```bash
modal run -m modal_3d.fastsam3d_plus_plus::sync_weights
./scripts/deploy-worker.ps1 modal_3d/fastsam3d_plus_plus.py
```
