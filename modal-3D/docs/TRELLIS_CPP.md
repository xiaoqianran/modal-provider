# trellis.cpp on Modal

Source: `pwilkin/trellis.cpp@16f3109e82f3922033bfa62b83c42899678b7b6f`.

## Production shape

- Native C++/GGML; Python only wraps the Modal class and localhost HTTP call.
- `modal-build` supplies a pinned CUDA 12.9.1 / SM89 binary bundle.
- CPU syncs only six F16 GGUF files required by 1024 geometry-only inference (~9.46 GB decimal).
- Texture flows/decoder and BiRefNet are excluded from the first Volume.
- Inputs are expected to be pre-matted RGBA so GPU background removal is unnecessary.
- `trellis-server` is started once in `@modal.enter`; requests reuse the resident CUDA backend.
- The upstream server serializes generation with a mutex; Modal additionally enforces one input per
  container and `max_containers=1`.

## Why server instead of CLI

The upstream server still stage-loads/frees GGUF models per request, but avoids reinitializing the GPU
backend for every job. This preserves low VRAM behavior while giving a meaningful warm-container path.

## Benchmark order

1. sync six F16 GGUF files on CPU
2. cold L40S container/server startup
3. first 1024 geometry-only request
4. three warm requests
5. compare against `hermit-trellis2-plus-plus` on the same pre-matted input
6. only then test Q8/Q4 and full texture mode
