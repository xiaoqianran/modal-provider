# modal-3D

## Non-negotiable runtime rules

- One independent Modal App/Image/weight Volume per model family.
- `max_containers=1` on every GPU model. A traffic spike must queue; it must never create a second GPU container.
- Do not enable container input concurrency. One warm model consumes one job at a time.
- Model weights are downloaded/synchronized by CPU-only functions and persisted in Modal Volume.
- GPU containers only mount local weights, load once with `@modal.enter()`, infer, and write results.
- `min_containers=0` initially. Pay for GPU only when jobs exist.

## Active model families

1. `hermit-trellis2-plus-plus` — first production benchmark target.
2. `hunyuan2.1-plus-plus`.
3. `fastsam3d-plus-plus` — fresh upstream clone reviewed; weights come from Fast-SAM3D upstream.

`sam3d-plus-plus` is intentionally excluded.

## Benchmark contract

Record separately for each model:

- image build duration
- CPU model download duration / bytes
- cold call wall time
- `@modal.enter()` model-load duration
- first inference duration
- warm inference duration (multiple runs)
- peak allocated/reserved VRAM
- artifact bytes
- estimated L40S compute cost per successful artifact

Never report a sampler-stage microbenchmark as end-to-end latency.
