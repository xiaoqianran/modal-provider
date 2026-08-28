# TRELLIS L40S comparison

Same benchmark input, seed 42, 1024 geometry-only intent, one L40S maximum, one input at a time.

| Metric | hermit-trellis2-plus-plus | trellis.cpp |
|---|---:|---:|
| Engine | PyTorch + Hermite/DMD | Native C++/GGML |
| CUDA | 12.4.1 | 12.9.1 |
| Torch | 2.6.0+cu124 | none |
| Build artifact | 191,019,883 B wheels.zip | 169,987,499 B runtime.tar.gz |
| Geometry weight storage | 24.35 GiB current full cache* | 8.81 GiB geometry-only F16 |
| First successful wall | 198.19 s clean cold | 130.63 s |
| Warm wall median | **11.98 s** | 120.67 s |
| Warm inference median | **10.17 s** | 113.14 s |
| Warm cost proxy @ $0.000542/s | **~$0.00650** | ~$0.06540 |
| Representative GLB | ~49.99 MB | ~276.74 MB |
| Runtime Python/PyTorch requirement | yes | no PyTorch; Python wrapper only |
| Quantized model path | not primary | native Q8/Q4 available |

`*` The current Hermite Volume includes auxiliary/full-pipeline assets and is not yet a geometry-only
trimmed cache, so its storage number is not a fair minimal-storage comparison.

## Current conclusion

For 1024 F16 geometry throughput on L40S, `hermit-trellis2-plus-plus` is currently the clear winner.
`trellis.cpp` is attractive for deployment simplicity, smaller geometry-only model storage, no PyTorch
runtime, and native Q8/Q4 options. It should be tested next at Q8/Q4 and/or 512 resolution rather than
assuming its F16/1024 path can compete on latency.

Both workers remain hard-limited to `max_containers=1` and one input at a time.
