# EmbodiedGen v2.1.0 on Modal L40S

This directory owns the Modal runtime for `HorizonRobotics/EmbodiedGen@v2.1.0`.
The production image is a release consumer: CUDA extensions are prebuilt and `nvcc` is intentionally absent at inference time.

## Production architecture

The image-to-3D hot path uses **one warm L40S container as the cache boundary**:

```text
VPS / local control plane
  ├─ validate request
  ├─ create Job ID / persist lightweight status
  └─ EmbodiedGenWorker.generate.spawn(...)
                 │
                 ▼
        one L40S container
        @modal.enter()
        ├─ BiRefNet-General-Lite (CUDA ONNX)
        └─ SAM3D resident model
                 │
                 ▼
        GPU BiRefNet background removal
                 │
                 ▼
        GPU SAM3D inference
                 │
                 ▼
        CPU mesh simplify + xatlas
        (same container, same process)
                 │
                 ▼
        GPU gsplat + TextureBaker
                 │
                 ▼
        CPU GLB / OBJ / URDF / validation
                 │
                 ▼
        one final Modal Volume commit
```

There are intentionally **no production** `RembgWorker`, `Sam3DWorker`, `MeshWorker`, `lite_gpu_bake`, or `cpu_finalize` stages anymore.
Intermediate Gaussian/mesh/texture state stays in-process instead of crossing Modal Dict/Volume boundaries.

### Runtime workers

| Worker | GPU | Idle policy | Purpose |
|---|---:|---:|---|
| `EmbodiedGenWorker` | L40S | 180 s | BiRefNet → SAM3D → mesh → texture → finalize |
| `Text2ImageWorker` | L40S | 5 s | Kolors front-end for Text→3D; immediately hands PNG bytes to `EmbodiedGenWorker` |
| `RetextureWorker` | L40S | 120 s | Prompt-driven retexture of a successful asset |

Affordance remains in its dedicated Modal apps plus the local control-plane orchestration in `embodiedgen_direct.py`.

## Text → 3D

Text-to-3D has exactly two GPU boundaries:

```text
VPS submit_text3d()
      │ spawn
      ▼
Text2ImageWorker / Kolors
      │ PNG bytes stay inside Modal
      │ spawn
      ▼
EmbodiedGenWorker
      │
      ▼
GLB / OBJ / URDF / video
```

The intermediate 1024px PNG is not downloaded to the VPS and uploaded again.
The Kolors worker uses a short 5-second handoff tail so it does not block the main 3D worker under constrained GPU concurrency.

## Local control plane

`runtime/embodiedgen_direct.py` is the VPS/local orchestrator. It owns:

- request validation;
- Job ID creation;
- lightweight Modal Dict job status;
- worker selection;
- detached `.spawn()` submission for Image→3D and Text→3D;
- result download from the artifact Volume;
- Retexture and Affordance orchestration.

It does **not** start a remote Modal CPU router and does not call `update_autoscaler()` per request.
Legacy profile names (`min_cost`, `cost_first`, `balanced`, `burst`) are accepted only as compatibility aliases; the production image-to-3D policy is fixed at `warm_180`.

## Storage model

Persistent objects:

- `modal-3d-embodiedgen-weights` → model weights and verified runtime caches;
- `modal-3d-artifacts` → final job artifacts;
- `modal-3d-embodiedgen-jobs` → lightweight job state.

The hot Image→3D path does not use Modal Volume as an inter-stage message bus and does not pickle SAM3D state through a Modal Dict.
Only final artifacts are durably published after successful finalize/validation.

## Models and pinned environment

| Component | Value |
|---|---|
| EmbodiedGen | v2.1.0 / `f0124197888c2b733e4eaa65acd81ad9cfda3b79` |
| Python | 3.10 |
| CUDA runtime | 12.6.3 |
| PyTorch | 2.8.0+cu126 |
| GPU | NVIDIA L40S / SM89 |
| SAM3D | `facebook/sam-3d-objects` |
| Background removal | BiRefNet-General-Lite, ONNX CUDA provider |
| Text→Image | `Kwai-Kolors/Kolors-diffusers` |
| Retexture | `xinjjj/RoboAssetGen` |

The runtime reuses the validated binary ABI bundle:

```text
embodiedgen-v2.0.0-py310-cu126-torch280-sm89-v1
```

This contains the pinned PyTorch3D/nvdiffrast/gsplat SM89 artifacts. Runtime cache misses must fail rather than compile CUDA on an L40S.

## Deploy

Run from the `modal-EmbodiedGen` repository root:

```bash
modal deploy modal/runtime/embodiedgen_v2_l40s.py
```

Prepare weights once:

```bash
modal run modal/runtime/embodiedgen_v2_l40s.py::preload_weights
modal run modal/runtime/embodiedgen_v2_l40s.py::preload_text2img_weights
modal run modal/runtime/embodiedgen_v2_l40s.py::preload_retexture_weights
```

## Benchmark

The current benchmark exercises the real unified cache boundary twice and requires the warm call to reuse the same resident instance:

```bash
modal run modal/runtime/embodiedgen_v2_l40s.py::benchmark_unified
```

The old split-worker benchmark and dynamic autoscale-profile benchmark have been removed.

## Validated production smoke results

The production Image→3D worker now uses three cold-start optimizations:

```text
1. BiRefNet uses native ONNX Runtime directly
   (no request-time import of the full rembg package)

2. SAM3D is local-only at runtime
   (no request-time ModelScope fallback/download path)

3. EmbodiedGenWorker uses Modal GPU Memory Snapshot
   enable_memory_snapshot=True
   experimental_options={"enable_gpu_snapshot": True}
```

### Startup profiling

Before the cold-start work, a representative resident initialization was:

```text
rembg/session import          ~39.6 s
EmbodiedGen/SAM3D import      ~15.8 s
SAM3D instantiate             ~23.7 s
BiRefNet CUDA session          ~2.6 s
resident initialization       ~84.3 s
```

After removing the `rembg` hot-path import, resident initialization dropped to about 44 seconds. With GPU Memory Snapshot, a verified snapshot hit restored the CPU/GPU model state and only rebuilt CUDA-bound BiRefNet state:

```text
GPU snapshot restore          handled by Modal
post-restore init              1.527 s
BiRefNet CUDA session          1.526 s
```

The restored worker reported `CUDAExecutionProvider` and `NVIDIA L40S`.

### Snapshot priming behavior

A new deployment may pay snapshot construction before steady-state restores. During validation:

```text
snapshot build #1             39.508 s
snapshot build #2             52.299 s
cold invocation #3            direct snapshot restore (no rebuild)
```

The third cold invocation contained `Restoring Function from memory snapshot` and did **not** emit `Creating GPU memory snapshot` or a new `EMBODIEDGEN_SNAPSHOT_BUILD` event.

### Image→3D: cold snapshot hit

A real cold Image→3D request after the warm container had naturally scaled to zero completed successfully:

```text
client wall                   85.261 s
post-restore init              1.527 s
BiRefNet                       0.700 s
SAM3D                         19.868 s
mesh / xatlas                  4.853 s
texture bake                   6.230 s
finalize                       4.241 s
pipeline total                40.039 s
```

The difference between pipeline time and client wall includes Modal GPU scheduling / container / snapshot infrastructure latency. The model no longer spends ~40 seconds importing and reconstructing SAM3D on this snapshot-hit path.

### Image→3D: warm reuse

The immediate follow-up request reused the exact same resident worker instance:

```text
instance_id                   9900ec452d814b61904d2a5a0d7fcf75
client wall                   37.338 s
BiRefNet                       0.243 s
SAM3D                          9.306 s
mesh / xatlas                  5.402 s
texture bake                   6.280 s
finalize                       4.374 s
pipeline total                32.510 s
```

Both the cold snapshot-hit and warm requests reached `succeeded / done`. Their GLBs were downloaded locally and identified as valid glTF 2.0 binary models; video and validation outputs also passed.

### Text→3D

Text→3D remains a two-GPU-boundary pipeline with Kolors handing image bytes directly to the unified worker. A validated representative run was:

```text
Kolors inference              11.870 s
BiRefNet                       0.618 s
SAM3D                         16.623 s
mesh                           4.123 s
texture                        3.713 s
finalize                       5.977 s
```


## Tests

The runtime architecture tests are source-level/unit tests and do not allocate a GPU:

```bash
PYTHONPATH=. python modal/tests/test_embodiedgen_job_api.py -v
```

Real deployment validation must additionally check:

1. `EmbodiedGenWorker` exists in the deployed app;
2. removed split workers return Modal `NotFoundError`;
3. a real Image→3D job reaches `succeeded / done`;
4. BiRefNet reports `CUDAExecutionProvider`;
5. output GLB/video/validation files are non-empty.

## Historical builder

`runtime/legacy/embodiedgen_v2_l40s_fullbuild.py` is retained only as a reproducible historical CUDA-build/validation reference. It is not deployed by the production runtime and is not part of the request path.
