# Pixal3D performance plan

Goal: reduce real user latency without silently reducing the recommended full-quality profile.

## Frozen reference profile

All optimization comparisons must keep these values fixed unless the result is explicitly labeled as a different quality tier:

- canonical input: same 1024x1024 RGBA PNG
- `pipeline_type=1536_cascade`
- `max_num_tokens=49152`
- `texture_size=4096`
- `decimation_target=1_000_000`
- `remesh=True`
- `seed=42`
- same camera mode

Report cold and warm runs separately. Never mix model load time into warm inference.

## Required timing breakdown

Every benchmark must report at least:

1. `load_s`
2. `camera_s`
3. `pipeline_s`
4. `glb_postprocess_s`
5. `glb_export_s`
6. `artifact_commit_s`
7. `worker_total_s`
8. client end-to-end time

The optimization target is chosen from measured stage contribution, not from total latency alone.

## Required GPU telemetry

For `camera`, `pipeline`, and `glb_postprocess`, record:

- GPU utilization average / p50 / p95 / max
- memory-controller utilization average
- peak VRAM
- PyTorch allocated/reserved stage peaks
- power average / max
- SM clock average

A large VRAM allocation is not evidence that the GPU is compute-saturated.

## Deploy the instrumented worker

From `modal-3D`:

```powershell
uv run modal run -m "modal_3d.pixal3d::sync_weights"
uv run modal deploy -m modal_3d.pixal3d
```

The existing `scripts/deploy-worker.ps1` performs the same sync-then-deploy sequence.

## Experiment order

### Gate A — L40S current software, instrumentation only

- GPU: L40S / SM89
- Torch 2.6.0 + CUDA 12.4
- attention: SDPA
- upstream stage-boundary `empty_cache()` behavior
- persistent FlexGEMM autotune cache enabled
- MoGe offloaded after camera estimation
- full-quality profile unchanged

Run the frozen canonical station benchmark:

```powershell
uv run python scripts/benchmark_pixal3d.py --variant sdpa-official --runs 2
```

The launcher creates an independently autoscaling class variant, measures cold bootstrap via `warmup()`, then runs the same worker repeatedly for warm measurements. Results are written as structured JSON under `benchmarks/runs/`.

Decision:

- if `glb_postprocess_s` dominates, optimize O-Voxel/mesh export before buying a faster tensor GPU;
- if `camera_s` is material, test MoGe residency on larger-memory GPUs;
- otherwise continue to Gate B and Gate C before changing the production backend.

### Gate B — allocator-cache A/B

This gate is executable with the existing SM89 artifact and therefore comes before adding another native dependency.

The pinned Pixal3D pipeline calls `torch.cuda.empty_cache()` at five full-GPU stage boundaries even when `low_vram=False`.

Compare Gate A with:

```powershell
uv run python scripts/benchmark_pixal3d.py --variant sdpa-no-stage-empty-cache --runs 2
```

Only `PIXAL3D_SUPPRESS_STAGE_EMPTY_CACHE` changes. Quality, seed, attention backend, source revision, allocator configuration and GLB export parameters stay fixed. The camera-path MoGe cleanup remains unchanged, so this specifically measures the five pipeline stage-boundary calls.

Acceptance:

- no OOM across the canonical stress set;
- peak reserved/allocated memory is recorded;
- median warm `pipeline_s` improves measurably before changing production default.

### Gate C — L40S FlashAttention-2 A/B

Keep Gate A quality and source revisions identical. Change only the attention implementation.

Candidate artifact:

- `pixal3d-py310-cu124-torch260-sm89-fa2-v1`
- derived from the existing six SM89 CUDA wheels; do not rebuild them
- FlashAttention 2.8.3 wheel matching Torch 2.6 / CPython 3.10 / CXX11 ABI false
- wheel SHA256 pinned to upstream GitHub Release metadata

The benchmark variant intentionally fails closed until that artifact is actually published and wired into the worker image. After that gate is opened:

```powershell
uv run python scripts/benchmark_pixal3d.py --variant fa2-official --runs 2
```

Acceptance:

- output GLB validates and is visually equivalent for the same seed/input;
- no increase in OOM/error rate;
- median warm `pipeline_s` improves by at least 10% before adopting the extra native dependency.

### Gate D — H100 native ceiling

Build a native SM90 runtime; do not reuse the SM89 wheel bundle.

- compatibility-first build: Python 3.10 + Torch 2.6 + CUDA 12.4
- all six CUDA extensions compiled for SM90 on H100
- upstream-pinned FlashAttention-3 wheel with release SHA256 verification
- FA3 CUDA forward smoke on the build H100 before publishing
- after correctness, benchmark CUDA 12.8 separately
- test MoGe resident on GPU
- same full-quality profile

This is the primary latency-ceiling experiment for Hopper.

### Gate E — RTX PRO 6000 native ceiling

Build and verify every CUDA extension for SM120. Do not infer compatibility from an SM89 or SM90 build.

Use the 96 GB VRAM to keep Pixal3D, DINO/NAF and MoGe resident where validated. Benchmark the best verified Blackwell attention backend; do not enable FlashAttention-4 solely because Pixal3D exposes the backend name.

## Cold-start track

Cold-start optimization is measured separately from warm inference:

1. baseline `@modal.enter()` model load;
2. Modal memory snapshot;
3. GPU snapshot only after the runtime is known to be snapshot-safe;
4. `min_containers=1` only as a latency/cost policy decision, not as an inference optimization.

## Success criteria

For each GPU/backend combination store a JSON benchmark record containing:

- source/build revisions
- GPU model and compute capability
- CUDA/Torch/Triton/attention versions
- quality profile
- cold bootstrap and warm stage timings
- telemetry summaries
- output size/hash/validation
- estimated cost per successful asset

Default-provider ordering may be changed only from measured warm/cold end-to-end records on the same canonical input and quality tier.
