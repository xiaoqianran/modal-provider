# Benchmarks

## TRELLIS2 / L40S — 2026-08-22

Environment: Python 3.11, CUDA 12.4.1, PyTorch 2.6.0+cu124, SM89, L40S. Native CUDA
wheels come from `xiaoqianran/modal-build` release
`trellis2-py311-cu124-torch260-sm89-v1`.

Production constraints: `max_containers=1`, no input concurrency, `min_containers=0`.

The first clean cold run after terminating all model containers measured **198.19 s client wall time**,
including **87.38 s model load** and **89.87 s first inference/JIT**. The immediately following warm
request measured **12.19 s wall / 11.17 s inference**.

Across four warm requests, median wall time is **11.98 s** and median model inference is **10.17 s**.
At the 2026-08-22 Modal L40S list price of $0.000542/s, the warm wall-time estimate is about
**$0.00650 per asset**. The cold client-wall estimate is about **$0.1074**. Client wall time is a
conservative cost proxy; billing should ultimately be reconciled against Modal's measured GPU runtime.

Weights and auxiliary HF assets occupy **26,150,307,654 bytes (~24.35 GiB)** in the model Volume.
A cached CPU sync completes in about **0.95 s**, so redeploys do not redownload the model.

The representative GLB is a valid glTF binary v2 file, ~47.7 MiB, with ~1.46M vertices and ~2.71M
faces. The benchmark uses a pre-masked RGBA image so background removal is intentionally outside the
GPU worker.
