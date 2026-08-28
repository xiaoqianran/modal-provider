# Benchmark safety and quality policy

Paid GPU benchmarks are **dry-run by default**. A full matrix is never the first operation.

## Quality baselines

| Model | Recommended benchmark profile | Quality status |
| --- | --- | --- |
| FastSAM3D++ | Fast-SAM3D official acceleration recipe, DMD off, runtime SS=25 / SLaT=25 | accelerated reference |
| Hunyuan2.1++ | base shape, 50 steps, Paint 6 views / 512, PBR, `paint_remesh=true` | full-quality; smoke required after remesh correction |
| Hermite-TRELLIS2++ | 1536 cascade, stock/base sampler, 4096 PBR, official remesh/to_glb | full-quality |
| Pixal3D | standard 1536 cascade, 12/12/12 sampler defaults, 49152 tokens, 4096 PBR | full-quality |

The FastSAM profile is an accelerated model profile, not the dense Meta SAM 3D Objects baseline. Its parameters match the public Fast-SAM3D recipe rather than a locally invented low-quality mode.

## Required execution order

1. Build the canonical input with `scripts/build_canonical.py`.
2. Run `scripts/run_pages_benchmark.py` without `--execute` and inspect the plan.
3. Execute **smoke only** (one scene per model). Each FunctionCall ID is atomically persisted before the command can exit.
4. Poll with `--resume`; polling never submits new GPU jobs.
5. Review all smoke results, then initialize full execution with `--full --execute --smoke-state ...`.
6. Full execution advances one scene per model per round. Poll each round with `--resume --full`, then explicitly submit the next round with `--advance --full`.
7. A failed model is a circuit breaker: no later scenes are submitted for that model.

Example:

```bash
python scripts/run_pages_benchmark.py --manifest benchmarks/my-scenes.json
python scripts/run_pages_benchmark.py --manifest benchmarks/my-scenes.json --execute
python scripts/run_pages_benchmark.py --manifest benchmarks/my-scenes.json --resume
python scripts/run_pages_benchmark.py \
  --manifest benchmarks/my-scenes.json \
  --full --execute --smoke-state /tmp/smoke.json --state /tmp/full.json \
  --max-calls 20 --max-estimated-gpu-seconds 6000
python scripts/run_pages_benchmark.py \
  --manifest benchmarks/my-scenes.json --full --resume --state /tmp/full.json \
  --max-calls 20 --max-estimated-gpu-seconds 6000
python scripts/run_pages_benchmark.py \
  --manifest benchmarks/my-scenes.json --full --advance --state /tmp/full.json \
  --max-calls 20 --max-estimated-gpu-seconds 6000
```

## Manifest

```json
{
  "scenes": [
    {
      "id": "house",
      "prompt": "an isometric small house",
      "canonical": "inputs/house.png",
      "modal_path": "client-inputs/<sha256>.png"
    }
  ]
}
```

The runner validates local canonical PNGs before any Modal call. Benchmark inputs with almost no RGB information inside the alpha foreground are rejected by default. For an intentionally black or near-black subject, set `"allow_low_information": true` on that specific manifest scene only after manual review; the exception then remains part of benchmark provenance.

## Provenance

Every recommended capability profile declares a quality tier and verification metadata. Reference latency is bound to a benchmark path and status (`verified`, `stale`, or `legacy`). A deployed profile/revision mismatch aborts benchmark execution before GPU submission.

## 2026-08-28 smoke result

All four production profiles passed the same repaired RGB+alpha biplane input. Worker inference times were FastSAM3D++ 5.01s, Hunyuan2.1++ 83.63s (29.89s shape + 53.74s paint), Hermite-TRELLIS2++ 228.82s, and Pixal3D 260.31s. See `benchmarks/full-quality-smoke-2026-08-28.json` for exact artifacts and metrics. This smoke validates correctness; it does not replace a multi-scene latency distribution.
