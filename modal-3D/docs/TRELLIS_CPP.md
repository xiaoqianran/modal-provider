# trellis.cpp on Modal / L40S

Source: `pwilkin/trellis.cpp@16f3109e82f3922033bfa62b83c42899678b7b6f`.

This document records the final production structure, actual L40S benchmark, packaging decisions, failures,
and lessons from integrating the native C++/GGML TRELLIS implementation. Read it together with
`benchmarks/trellis.cpp-l40s-2026-08-22.json`, `benchmarks/COMPARISON.md`, and
`docs/ENGINEERING_RETROSPECTIVE.md`.

## 1. Why trellis.cpp is a separate worker

`trellis.cpp` is not a Python rewrite of the Hermite worker. It is a native C++17/GGML implementation with a
materially different deployment and execution model.

Key runtime properties:

- no PyTorch dependency for the inference engine;
- GGUF checkpoints;
- native GGML CUDA backend;
- native CLI and HTTP server;
- native `--no-texture` geometry mode;
- F16, Q8 and Q4 model options;
- staged model load/free behavior to constrain GPU memory.

Production identity:

```text
Modal App:      modal-3d-trellis.cpp
Module:         modal_3d/trellis_cpp.py
GPU:            L40S
max_containers: 1
min_containers: 0
Concurrency:    one input at a time
```

## 2. Source and CUDA architecture

The integration pins:

```text
pwilkin/trellis.cpp
commit 16f3109e82f3922033bfa62b83c42899678b7b6f
```

The upstream CMake configuration included CUDA architecture choices that did not directly target L40S SM89.
The Modal build therefore explicitly compiles for:

```text
GGML_CUDA=ON
CMAKE_CUDA_ARCHITECTURES=89
```

This is a native L40S/SM89 build, not a generic prebuilt CUDA bundle.

## 3. `modal-build` native bundle

Because this project is native C++, the artifact is not a wheel set. `modal-build` publishes a runtime tarball.

Current release:

`trellis.cpp-pynone-cu129-torchnone-sm89-v2`

Environment identity:

```text
Python       none for inference engine
PyTorch      none
Ubuntu       22.04
CUDA         12.9.1
GPU          L40S
CUDA arch    SM89
Backend      GGML_CUDA
```

The production worker uses Python only as a thin Modal wrapper around the resident native HTTP server.

The v2 bundle contains only compiled project artifacts such as:

- `trellis-server`
- `trellis-cli`
- `libggml*.so`

CUDA runtime libraries are supplied by the pinned NVIDIA runtime image.

## 4. Why v1 was too large

The first native bundle attempted to be self-contained and copied CUDA runtime libraries into the Release.
That duplicated libraries already present in `nvidia/cuda:12.9.1-runtime-ubuntu22.04`.

The largest offender was `libcublasLt`, making the archive unnecessarily large.

Observed bundle size change:

```text
v1 ~716 MiB
v2 ~162 MiB
```

This was an important packaging lesson: a self-contained archive is not automatically better when the base
runtime image is already part of the compatibility contract.

## 5. Runtime dependency validation

The builder checks native runtime dependencies with `ldd` before publishing.

An early version incorrectly rejected:

```text
libcuda.so.1 => not found
```

in the non-GPU build environment. That library is expected to be injected/provided by the NVIDIA driver at GPU
runtime and should not be shipped with the app.

The correct validation policy is:

- unresolved application/runtime dependencies -> fail build;
- driver-owned `libcuda.so.1` -> allowed in the builder;
- verify the actual GPU container starts successfully afterward.

`libgomp.so.1` was a real missing runtime dependency and is installed via `libgomp1` in the production image.

## 6. Geometry-only checkpoint set

Unlike the Python Hermite pipeline, `trellis.cpp` natively supports `--no-texture`. The first production profile
therefore does not need to load texture models at all.

F16 geometry-only Volume contains six GGUF files:

```text
dinov3.gguf
ss_flow.gguf
ss_dec.gguf
shape_flow_512.gguf
shape_flow_1024.gguf
shape_dec.gguf
```

Measured total:

```text
9,462,658,720 bytes
~8.81 GiB
```

The full F16 model family is substantially larger because it also includes texture models and background
removal. Geometry-only storage is one of `trellis.cpp`'s strongest operational advantages.

Native quantized paths also exist:

```text
F16 geometry ~9.46 GB decimal
Q8  geometry ~5.48 GB approximate
Q4  geometry ~3.36 GB approximate
```

Q8/Q4 were intentionally left for a separate quality/performance benchmark instead of mixing them into the
first F16 comparison.

## 7. CPU-only weight sync

The six GGUF files are downloaded by a CPU Modal function into:

```text
modal-3d-trellis.cpp-f16-geometry
```

The GPU worker does not download weights. Texture checkpoints and BiRefNet are not present in this geometry
Volume.

Input is expected to be pre-matted RGBA, matching the same product-level preprocessing rule used by the
Hermite worker.

## 8. Why use `trellis-server` instead of the CLI per request

The upstream project ships both `trellis-cli` and a resident HTTP server.

Starting a CLI process per job would repeatedly initialize process-level CUDA/GGML state. The production worker
therefore starts `trellis-server` once in `@modal.enter()` and sends generation requests over localhost.

However, source inspection showed an important limitation: the resident server does **not** keep every model
fully resident on GPU between requests. It still stage-loads/frees GGUF model components for generation.

Therefore server residency saves process/backend initialization, but it does not turn a warm request into a
fully resident-model path.

## 9. Cancellation and child-process ownership

A failed/cancelled Modal Python call initially could leave the native `trellis-server` continuing to perform GPU
work in the background.

The worker now owns the subprocess explicitly:

```text
@modal.enter  -> start server
request error -> terminate server
next request  -> restart if needed
@modal.exit   -> terminate server
```

This prevents cancelled calls from silently consuming L40S time after the Modal request is gone.

## 10. A supposed "crash" was actually an external stop

One early long inference appeared to have crashed because the client received cancellation/termination signals.
Modal logs showed otherwise:

- L40S initialized correctly;
- compute capability 8.9 was detected;
- sparse/shape stages ran;
- a very large mesh was decoded;
- the application was stopped externally from the dashboard.

The termination line was effectively:

```text
Stopping app - user stopped from dashboard.
Runner terminated.
```

It was not a CUDA OOM, kernel failure, segfault, or model exception.

The lesson is to inspect platform termination events before changing model code.

## 11. Benchmark methodology

The F16 benchmark uses the same pre-matted RGBA sample/seed class as the Hermite comparison:

```text
512 x 512 RGBA
SHA256 a1d79ae86f849587e2acff26b34acc749a0d2900febb57748c9d87193394fc82
seed 42
resolution 1024
geometry only
L40S
max_containers=1
```

The first fully successful run is recorded separately from the three warm runs. It is called
`first_successful_run` rather than a guaranteed clean-cold measurement because the experimental lifecycle was
not as strictly isolated as the later Hermite/Pixal3D clean-cold procedure.

## 12. Measured F16/1024 performance

First successful run:

```text
client wall       130.63 s
server startup      0.32 s
inference          117.02 s
```

Warm runs:

```text
wall        inference
120.818 s   115.261 s
117.915 s   112.730 s
120.668 s   113.141 s
```

Warm median:

```text
wall        120.67 s
inference   113.14 s
```

Representative artifact:

```text
276,743,212 bytes
~264 MiB
glTF Binary v2
```

At the L40S rate used in the benchmark (`$0.000542/s`), warm client-wall cost proxy is roughly:

```text
~$0.0654 per asset
```

## 13. Why the resident server does not become fast when warm

The measured server startup is only about `0.32 s`, yet warm inference remains ~113 s. This proves that
process startup is not the dominant cost.

Log/source analysis showed expensive work in the actual model path, especially:

```text
sparse structure        several seconds
shape LR                several seconds
shape HR 1024           ~tens of seconds, around the largest stage
mesh/FlexiDualGrid      substantial additional time
hole filling/export     additional cost
```

Because model stages are still loaded and executed per request, keeping the HTTP server alive cannot remove
those costs.

This is an example of why "native resident service" must not be assumed to mean "resident model".

## 14. Output-size caveat in performance comparisons

The `trellis.cpp` benchmark produced a much larger GLB than the Hermite geometry benchmark:

```text
hermit-trellis2-plus-plus ~49.99 MB
trerellis.cpp             ~276.74 MB
```

Intermediate `trellis.cpp` logs also showed multi-million-vertex / multi-million-face meshes.

Therefore the ~12 s vs ~121 s warm comparison is highly relevant operationally but not a perfectly equal
quality/mesh-complexity comparison. Future benchmark matrices should normalize at least:

- input;
- seed;
- resolution;
- texture mode;
- decimation target;
- triangle count/output complexity;
- quantization;
- step counts where configurable.

## 15. Comparison with hermit-trellis2-plus-plus

Current measured 1024 geometry result:

```text
hermit-trellis2-plus-plus warm wall ~11.98 s
trellis.cpp F16 warm wall          ~120.67 s
```

For throughput on L40S, the Hermite fork wins by roughly an order of magnitude in this tested configuration.

`trellis.cpp` still has meaningful advantages:

- no PyTorch inference runtime;
- much smaller geometry-only checkpoint storage;
- compact native runtime bundle;
- native Q8/Q4 options;
- straightforward geometry-only mode;
- lower dependency complexity.

These properties may make it attractive as a low-storage/economy profile even when F16/1024 latency is not
competitive.

## 16. What should be benchmarked next if this worker is revisited

Do not spend effort optimizing the 0.32 s server startup. The relevant experiments are:

1. Q8 / 1024 geometry;
2. Q4 / 1024 geometry;
3. F16 / 512 geometry;
4. Q8 / 512 geometry;
5. explicit mesh/decimation normalization against Hermite;
6. full texture mode only after geometry profiles are understood.

The purpose is to find `trellis.cpp`'s best operating point, not force it to imitate the Hermite implementation.

## 17. Important integration mistakes and lessons

### CMake version mismatch

Ubuntu 22.04's system CMake was too old for the repository's current FetchContent usage. The build now installs
modern CMake/Ninja via `uv` instead of relying on the distro CMake.

### Upstream CUDA architecture assumptions

The source did not directly target L40S SM89 in the desired way. Build architecture is explicitly pinned to 89.

### Missing OpenMP runtime

The native binary compiled successfully but failed in the production runtime because `libgomp.so.1` was absent.
Compiled artifact success must be followed by clean-runtime dynamic dependency validation.

### Overpacking CUDA runtime

Shipping NVIDIA runtime libraries inside the app bundle increased v1 from a compact project bundle to ~716 MiB.
The base CUDA runtime image should own those dependencies.

### `libcuda.so.1` is driver-owned

A builder without a GPU will not necessarily resolve it. It should not be copied into a release bundle.

### External stop is not a model crash

Modal logs, not the client symptom, determine why a container ended.

### Cancellation does not automatically stop child GPU work

Native subprocess lifecycle must be tied explicitly to Modal request/container lifecycle.

## 18. Current conclusion

`trellis.cpp` is a successful production-quality integration in the sense that it is reproducible, compact,
CPU-preloaded, GPU-offline, single-container, and capable of producing real GLB output on L40S.

It is **not** currently the fastest TRELLIS worker for our tested F16/1024 geometry workload.

Its value is architectural simplicity and alternative operating points (especially quantization), while
`hermit-trellis2-plus-plus` remains the current latency leader.
