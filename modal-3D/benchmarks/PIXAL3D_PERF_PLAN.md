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
- same seed and camera mode

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
8. `job_total_s`

The optimization target is chosen from measured stage contribution, not from total latency alone.

## Required GPU telemetry

For `camera`, `pipeline`, and `glb_postprocess`, record:

- GPU utilization average / p50 / p95 / max
- memory-controller utilization average
- peak VRAM
- power average / max
- SM clock average

A large VRAM allocation is not evidence that the GPU is compute-saturated.

## Experiment order

### Gate A — L40S current software, instrumentation only

- GPU: L40S / SM89
- Torch 2.6.0 + CUDA 12.4
- attention: SDPA
- persistent FlexGEMM autotune cache enabled
- MoGe offloaded after camera estimation
- full-quality profile unchanged

Run one cold invocation followed by at least two warm invocations in the same container. Then force a new container and verify the persisted FlexGEMM cache is reused.

Decision:

- if `pipeline_s` dominates and pipeline GPU utilization is not near saturation, proceed to Gate B;
- if `glb_postprocess_s` dominates, optimize O-Voxel/mesh export before buying a faster tensor GPU;
- if `camera_s` is material, test MoGe residency on larger-memory GPUs.

### Gate B — L40S FlashAttention-2 A/B

Keep Gate A quality and source revisions identical. Change only the attention implementation.

Candidate artifact:

- L40S / SM89
- Python 3.10
- Torch 2.6.0
- CUDA 12.x
- FlashAttention 2.8.3 wheel matching Torch 2.6 / CPython 3.10 / CXX11 ABI

Acceptance:

- output GLB validates and is visually equivalent for the same seed/input;
- no increase in OOM/error rate;
- median warm `pipeline_s` improves by at least 10% before adopting the extra native dependency.

### Gate C — allocator-cache A/B

The pinned Pixal3D pipeline calls `torch.cuda.empty_cache()` between multiple full-GPU stages even when `low_vram=False`.

Compare:

- upstream behavior: stage-boundary `empty_cache()` enabled;
- full-GPU behavior: stage-boundary `empty_cache()` suppressed while keeping `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.

Acceptance:

- no OOM across the canonical stress set;
- peak reserved/allocated memory is recorded;
- warm `pipeline_s` must improve measurably before changing production default.

### Gate D — H100 native ceiling

Build a native SM90 runtime; do not reuse the SM89 wheel bundle.

- CUDA 12.8 preferred for the FlashAttention-3 benchmark
- FlashAttention-3 backend
- all Pixal3D/DINO models resident
- test MoGe resident on GPU
- same full-quality profile

This is the primary latency-ceiling experiment for Hopper.

### Gate E — RTX PRO 6000 native ceiling

Build and verify every CUDA extension for SM120. Do not infer compatibility from an SM89 or SM90 build.

Use the 96 GB VRAM to keep Pixal3D, DINO/NAF and MoGe resident where validated. Benchmark the best verified Blackwell attention backend; do not enable FlashAttention-4 solely because Pixal3D exposes the backend name.

## Cold-start track

Cold-start optimization is measured separately from inference:

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
- cold and warm stage timings
- telemetry summaries
- output size/hash/validation
- estimated cost per successful asset

Default-provider ordering may be changed only from measured warm/cold end-to-end records on the same canonical input and quality tier.
