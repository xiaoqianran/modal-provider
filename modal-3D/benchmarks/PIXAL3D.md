# Pixal3D / L40S

Production benchmark for `TencentARC/Pixal3D@cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af`.
The worker uses one L40S maximum, one input at a time, Python 3.10, CUDA 12.4.1, PyTorch 2.6.0,
NATTEN 0.21.0 and SDPA. Six SM89 native wheels are installed from the public `modal-build` release
`pixal3d-py310-cu124-torch260-sm89-v1`; the runtime image does not compile CUDA extensions.

The clean fixed-FOV cold request measured **288.31 s wall**, including **76.89 s model load** and
**189.23 s inference / first-run autotuning**, with **31.37 GiB peak board VRAM**. Three subsequent
warm requests measured **108.92 / 111.31 / 104.81 s wall**, with a **108.92 s median** and
**99.39 s median inference**. Warm peak VRAM was **30.49 GiB**.

At an L40S rate of $0.000542/s, client-wall-time cost proxies are approximately **$0.1563 cold** and
**$0.0590 warm**. These are conservative wall-time proxies rather than authoritative Modal billing.

A representative textured GLB is **33,789,572 bytes** and validates as glTF Binary v2. The separate
`fov=None` path using MoGe also completed successfully and produced a **36,338,124-byte** GLB; that
run started a fresh container and is recorded only as a functional validation, not warm performance.

The production path intentionally removes BiRefNet from the GPU worker and requires a pre-matted RGBA
input. `low_vram=False` is viable on L40S for this configuration; observed peak stayed well below 48 GB.
