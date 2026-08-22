# modal-3D deployment plan

## Contract

All model services expose the same logical operation:

`generate(input_path: str, options: dict) -> {model, output_path, elapsed_s}`

The CPU gateway only submits jobs and polls `FunctionCall`; it never imports torch or touches a GPU.

## Storage

- One Modal Volume per model family for model weights and compile/runtime assets.
- A CPU-only sync function downloads Hugging Face / release assets into the Volume.
- GPU workers run offline against local Volume paths.
- Inputs/results should ultimately live in object storage or a dedicated jobs Volume; the local APP can upload first and submit only a path/URL.

## GPU policy

Start with L40S (48 GB) for all four workers. Benchmark RTX PRO 6000 only after L40S baselines exist.
Do not keep `min_containers > 0` initially. Keep `scaledown_window` short (60 s) until traffic data says otherwise.

## Isolation

Use four separate Modal Apps/images:

- `modal-3d-hunyuan`
- `modal-3d-sam3d`
- `modal-3d-fastsam3d`
- `modal-3d-trellis2`

This avoids dependency collisions and lets each model evolve independently while preserving one API contract.

## Benchmark phases

For every service record separately:

1. image build time
2. CPU weight download bytes/time
3. cold container startup
4. weight load / GPU-ready time
5. first inference after cold start
6. warm inference p50 over >=5 runs
7. peak VRAM
8. output size
9. estimated $ / successful asset on L40S and RTX PRO 6000

Never mix model-load time into warm inference numbers.
