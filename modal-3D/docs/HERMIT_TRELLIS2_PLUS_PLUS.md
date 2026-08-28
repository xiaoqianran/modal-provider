# hermit-trellis2-plus-plus on Modal / L40S

Source: `Archerkattri/hermit-trellis2-plus-plus@2c8402a92ea97c510c09e278fae557771aad774d`.

This document records the production shape, benchmark evidence, mistakes encountered during integration,
and the reasoning behind the final deployment structure. It should be read together with
`benchmarks/hermit-trellis2-plus-plus-l40s-2026-08-22.json` and `docs/ENGINEERING_RETROSPECTIVE.md`.


## Current production quality profile

The current recommended profile is `1536_cascade`, `acceleration=base`, and `texture_size=4096`. `base` restores the stock TRELLIS.2 samplers; GLB export matches Microsoft's public high-quality example (`remesh=True`, 1,000,000 decimation target, 4096 PBR textures). Older 1024/Hermite-DMD sections below are historical benchmark records, not the current recommended profile.

The current 1536/base reference is `benchmarks/pages-pinterest-a1-quality-2026-08-24.json` (~297.25s worker inference).

## 1. What this worker is

This worker is the Python/PyTorch/Hermite-DMD implementation of TRELLIS.2. It is intentionally named after
the exact fork being measured: `hermit-trellis2-plus-plus`.

Do not shorten it to `trellis2` in benchmark names or public identifiers. That became ambiguous as soon as
`pwilkin/trellis.cpp` was integrated as a second TRELLIS implementation.

Production identity:

```text
Modal App:     modal-3d-hermit-trellis2-plus-plus
Module:        modal_3d/hermit_trellis2_plus_plus.py
GPU:           L40S
max_containers 1
min_containers 0
Concurrency:   one input at a time
```

The current physical weight Volume still uses the legacy internal name `modal-3d-trellis2-weights` to avoid
redownloading ~24.35 GiB. That Volume name is an implementation detail, not the model identity.

## 2. Runtime environment

Pinned runtime/build compatibility:

```text
Python       3.11
Ubuntu       22.04
CUDA         12.4.1
PyTorch      2.6.0+cu124
torchvision  0.21.0+cu124
GPU          NVIDIA L40S
CUDA arch    SM89
Attention    flash-attn
Acceleration Hermite / DMD
```

The expensive native components are not compiled in the production worker. They are published once from
`modal-build` as:

`hermit-trellis2-plus-plus-py311-cu124-torch260-sm89-v1`

The Release contains prebuilt wheels for:

- `flash-attn==2.7.3`
- CuMesh
- FlexGEMM
- o-voxel

The production image downloads the Release zip, extracts it, and installs the wheels. Rebuilding a Modal
runtime image therefore does not recompile these CUDA extensions.

## 3. Why `modal-build` was necessary

The initial implementation compiled native CUDA extensions directly while building the inference image.
That exposed several problems:

1. CuMesh could not auto-detect a CUDA architecture in a CPU builder and failed with an empty architecture
   list.
2. A long native image build was externally terminated even though the source was not invalid.
3. `o-voxel` expected Eigen headers under `third_party/eigen`, but the checked-out source did not contain the
   required contents there.
4. Repeating those compilations would waste both time and GPU build cost on every image rebuild.

The stable rule became:

```text
compile once on a compatible builder
        ↓
modal-build Release
        ↓
production image installs binaries only
```

SM89 is always explicit. The builder does not depend on GPU auto-detection:

```text
TORCH_CUDA_ARCH_LIST=8.9
CC=gcc
CXX=g++
```

Native `pip wheel` calls use `--no-deps`. This prevents the wheelhouse from silently pulling an incompatible
newer Torch/CUDA stack.

## 4. Weight acquisition is CPU-only

The main checkpoint alone is not sufficient. Source/config inspection showed external model dependencies.
The CPU sync stage caches:

- `microsoft/TRELLIS.2-4B`
- `microsoft/TRELLIS-image-large`
- `facebook/dinov3-vitl16-pretrain-lvd1689m`
- `ZhengPeng7/BiRefNet`

DINOv3 is gated. Anonymous download returned HTTP 401, so the existing Modal `huggingface` Secret is attached
only to `sync_weights()`.

The GPU worker does not receive the Hugging Face credential and starts with offline mode enabled:

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

This makes missing-cache bugs fail explicitly instead of letting an expensive L40S sit idle while downloading.

Current cached storage:

```text
26,150,307,654 bytes
~24.35 GiB
```

After the Volume is populated, a repeated CPU sync completes in about `0.95 s` because the model is already
present.

## 5. Background removal belongs outside the L40S path

The first RGB test revealed that BiRefNet loading/caching could block a fully offline GPU startup. More
importantly, it exposed an architectural mistake: for the product path we can require or generate a pre-matted
RGBA image before the 3D model sees the input.

The benchmark therefore uses an RGBA input with a real alpha mask. TRELLIS skips background removal and the
expensive GPU worker performs only the 3D path.

Preferred product flow:

```text
user image
   ↓
CPU / preprocessing service
   ↓
RGBA + alpha mask
   ↓
queue
   ↓
ONE L40S
   ↓
hermit-trellis2-plus-plus
```

The current Volume still contains BiRefNet because it was part of the original full pipeline cache. A future
geometry-only cache can remove it completely.

## 6. Current inference path

The worker loads the pipeline once in `@modal.enter()`:

```text
Trellis2ImageTo3DPipeline.from_pretrained(...)
        ↓
.to("cuda")
        ↓
enable_faster()
        ↓
sparse_structure_sampler.hicache_backend = "dmd"
```

Each `generate()` call then runs:

```text
pre-matted RGBA
  ↓
1024_cascade
  ↓
Hermite/DMD accelerated sampling
  ↓
mesh
  ↓
geometry-only GLB export with trimesh
```

The first validation GLB deliberately exports vertices/faces only. It does not attempt textured/PBR output.
That decision was made to prove the core image-to-mesh path before adding expensive rendering/texture
postprocessing.

## 7. Benchmark methodology

Benchmark input:

```text
512 x 512 synthetic pre-matted RGBA object
SHA256 a1d79ae86f849587e2acff26b34acc749a0d2900febb57748c9d87193394fc82
pipeline 1024_cascade
L40S
max_containers=1
one request at a time
```

One early result was incorrectly tempting to label as "cold" because it was the first successful request.
However, a previous failed background-removal request had left the container alive. The benchmark was repeated
after explicitly stopping/redeploying the app to obtain a truly clean container.

## 8. Measured performance

Clean cold:

```text
client wall time     198.19 s
@modal.enter load     87.38 s
first inference/JIT   89.87 s
```

Warm runs:

```text
wall       inference
12.297 s   10.452 s
11.706 s    9.829 s
11.781 s    9.898 s
12.186 s   11.171 s
```

Warm medians:

```text
wall       11.98 s
inference  10.17 s
```

Representative GLB:

```text
49,986,864 bytes
1,458,257 vertices
2,707,250 faces
glTF Binary v2
```

At the L40S list rate used for this benchmark (`$0.000542/s`), client-wall-time cost proxies are roughly:

```text
cold  ~$0.1074
warm  ~$0.00650
```

These are comparison proxies, not authoritative Modal invoice values.

## 9. VRAM interpretation

The first benchmark recorded PyTorch allocator values:

```text
peak allocated ~2.94 GiB
peak reserved  ~3.48 GiB
```

This is **not** total board-level L40S VRAM use. The pipeline stages/offloads work and PyTorch allocator
telemetry does not represent all GPU memory consumers. Do not advertise "TRELLIS needs 3.5 GB" from this
number.

Future benchmarks should prefer board-level telemetry (`nvidia-smi`) when comparing memory requirements.

## 10. Why warm performance is good

The large cold/warm difference is the most important result:

```text
cold wall ~198 s
warm wall ~12 s
```

The warm path benefits from:

- pipeline object already constructed;
- checkpoints already deserialized;
- model state already prepared;
- CUDA/runtime initialization already complete;
- first-run kernels/JIT already exercised;
- Hermite/DMD acceleration active.

This is why the production architecture must keep one model instance alive per warm container rather than
recreating the pipeline for every job.

## 11. Why this is not yet the absolute optimal geometry worker

A deeper source/config inspection showed that the current full `Trellis2ImageTo3DPipeline.from_pretrained()`
loads components for texture generation even though the first product endpoint only exports geometry.

The full pipeline contains shape and texture flow/decoder components. If the geometry endpoint can construct a
minimal pipeline using only:

```text
image encoder
sparse structure
shape 512
shape 1024
shape decoder
```

then it should be possible to avoid loading/running:

```text
texture flow 512
texture flow 1024
texture decoder
```

This is the next meaningful optimization because it can reduce checkpoint I/O, model load, GPU transfer,
first-run work, warm inference, and storage at the same time.

Do not optimize tiny import/install details before measuring this larger source-level opportunity.

## 12. Cold-start optimization priorities

The cold path currently decomposes approximately into:

```text
198.19 s total
├─ 87.38 s model load
├─ 89.87 s first inference/JIT
└─ ~20.9 s scheduler/container/other wall overhead
```

Therefore the correct optimization order is:

1. geometry-only component trimming;
2. profile each checkpoint load/deserialization step;
3. profile CPU->GPU/model movement;
4. identify first-inference CUDA/JIT cost;
5. test controlled prewarm;
6. only then test Modal memory snapshots;
7. tune `scaledown_window` after real traffic/cost data exists.

Blindly enabling snapshots before understanding the 87 s vs 90 s split would make the benchmark harder to
interpret.

## 13. Queueing and scaling contract

This project deliberately optimizes for bounded cost rather than arbitrary parallelism.

```text
max_containers=1
no @modal.concurrent
one request per container
```

If 100 requests arrive, they queue. Modal must not create a second `hermit-trellis2-plus-plus` L40S container.

This limit is per model family. A separate local/global scheduler may later enforce one GPU job globally across
multiple model families if desired.

## 14. Important integration mistakes and lessons

### Wrong public name

Shortening the fork to `trellis2` made later comparisons ambiguous. Public artifacts now use the full fork
name.

### Incomplete model dependency enumeration

The main TRELLIS checkpoint did not imply all external condition/rembg models were available. Source and config
search is required before claiming offline readiness.

### Gated model discovered only during sync

DINOv3 forced an authenticated CPU download. The correct response was not to give HF credentials to the GPU;
it was to put the credential on `sync_weights()` only.

### BiRefNet failure exposed an architectural simplification

Instead of making GPU-side rembg more robust, pre-matted RGBA input made rembg unnecessary for the measured
endpoint.

### First successful request was not a cold request

A container can survive a failed request. Cold benchmarks require an explicitly fresh container.

### Long native compilation should never live in the production image

CuMesh/FlexGEMM/o-voxel/flash-attn are build artifacts. Their compilation belongs in `modal-build`.

## 15. Current conclusion

For the tested 1024 geometry path on L40S, `hermit-trellis2-plus-plus` is currently the fastest TRELLIS
implementation in this project by a large margin:

```text
warm wall median ~11.98 s
```

Its tradeoff is a heavier Python/PyTorch runtime and a currently over-complete ~24.35 GiB checkpoint cache.

The next optimization should be a measured geometry-only component trim, not architectural rewrites or extra
GPU containers.
