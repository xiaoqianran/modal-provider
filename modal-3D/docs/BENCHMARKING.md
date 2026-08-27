# Benchmark safety and quality policy

Paid GPU benchmarks are **dry-run by default**. A full matrix is never the first operation.

## Quality baselines

| Model | Recommended benchmark profile | Quality status |
| --- | --- | --- |
| FastSAM3D++ | Fast-SAM3D official acceleration recipe, DMD off, SS=2 / SLaT=12 | accelerated reference |
| Hunyuan2.1++ | base shape, 50 steps, Paint 6 views / 512, PBR, `paint_remesh=true` | full-quality; smoke required after remesh correction |
| Hermite-TRELLIS2++ | 1536 cascade, stock/base sampler, 4096 PBR, official remesh/to_glb | full-quality |
| Pixal3D | standard 1536 cascade, 12/12/12 sampler defaults, 49152 tokens, 4096 PBR | full-quality |

The FastSAM profile is an accelerated model profile, not the dense Meta SAM 3D Objects baseline. Its parameters match the public Fast-SAM3D recipe rather than a locally invented low-quality mode.

## Required execution order

1. Build the canonical input with `scripts/build_canonical.py`.
2. Run `scripts/run_pages_benchmark.py` without `--execute` and inspect the plan.
3. Execute **smoke only** (one scene per model). The default call budget is four.
4. If every required model passes, run the full matrix with explicit `--full`, `--max-calls`, and GPU-second budget increases.
5. A failure on a model's smoke is a circuit breaker: later scenes for that model are not submitted.

Example:

```bash
python scripts/run_pages_benchmark.py --manifest benchmarks/my-scenes.json
python scripts/run_pages_benchmark.py --manifest benchmarks/my-scenes.json --execute
python scripts/run_pages_benchmark.py \
  --manifest benchmarks/my-scenes.json \
  --execute --full \
  --max-calls 20 \
  --max-estimated-gpu-seconds 6000
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

The runner validates local canonical PNGs before any Modal call. Benchmark inputs with almost no RGB information inside the alpha foreground are rejected by default. Use the low-information override only when the subject is intentionally black or near-black and the source has been manually reviewed.

## Provenance

Every recommended capability profile declares a quality tier and verification metadata. Reference latency is bound to a benchmark path and status (`verified`, `stale`, or `legacy`). A deployed profile/revision mismatch aborts benchmark execution before GPU submission.
