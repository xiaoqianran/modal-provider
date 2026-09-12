# Fire3D official reproduction in modal-fire3d

This integration mirrors the public Fire3D release instead of reimplementing the model.

## Pinned release

- Upstream: `xiahongchi/Fire3D`
- Revision: `2368dd2f3909120cf90bbf8a17807abe9c41e600`
- First reproduction dataset: `single_image`
- First reproduction scene: `003025`
- Frozen protocol: `configs/inference/fire3d_single_image_v1.json`
- Runtime baseline: Python 3.10, CUDA 12.8, PyTorch 2.7.1
- Initial Modal GPU: H100 (sm90)

The H100 profile is intentionally the first Modal target because the public release depends on
multiple CUDA extensions. Blackwell/RTX PRO 6000 is a later compatibility and performance gate,
not a silent change to the first reproduction baseline.

## Important input contract

The public `single_image` release protocol does **not** currently accept an arbitrary RGB file by
itself. Its published dataset adapter expects:

```text
data/single_image/
  single_image_valid.txt
  data/<scene_id>/
    rgb.jpeg
    aligned_pcd.ply
    camera.json       # needed for input-camera views/rendering
```

Therefore this integration does not yet claim generic `PNG -> Fire3D world`. Raw RGB -> Pi3/aligned
point-cloud preprocessing must be wired and verified as a separate stage.

## Isolation boundary

Fire3D is a separate package and deployment:

```text
modal-fire3d/
  modal_fire3d/
    backend.py
    runtime.py
    app.py
    deployment.py
```

The Modal app is `modal-world-fire3d`. It has independent model, data, and output volumes and does
not share the HYWorld2 Python/CUDA environment.

## Official smoke gate

From `modal-provider/modal-fire3d`:

```powershell
uv sync --extra dev
uv run modal deploy -m modal_fire3d.app
uv run modal run -m modal_fire3d.app::preload_official_single_image
uv run modal run -m modal_fire3d.app::official_single_image_smoke
```

If the CLI version does not accept `-m` for `run`, use the module form shown by `modal run --help`.

The default smoke passes `--skip-render`; it still exercises Fire3D perception, reconstruction,
per-object PBR GLB export, and composed-world GLB export. It intentionally skips Blender rendering
so the first gate measures the reconstruction system rather than the visualization layer.

A successful run must contain at least:

```text
summary.json
resolved_protocol.json
reconstruction/003025/inference_summary.json
reconstruction/003025/appearance/appearance_summary.json
reconstruction/003025/appearance/predicted_textured_world_scene.glb
reconstruction/003025/**/canonical.glb
```

`inference_summary.json.status` must equal `complete` and at least one independent object
`canonical.glb` must exist.

## Provider exposure policy

Use `modal_fire3d.service.execute` or `modal_fire3d.backend.Fire3DBackend` explicitly.
FIRE3D is no longer registered by `modal_world.service` or deployed by its manifest.
The existing AgentScape-facing `ModalWorldProvider` continues to expose HYWorld2.
The only shared Python interfaces are `modal_world.backend` and `modal_world.contracts`;
installing the local `modal-world` dependency does not install HYWorld2/Torch/CUDA.

For `service.execute`, `input_path` (or `options.data_root`) is the parent of
`single_image/`, matching the upstream CLI's `--data-root`, not the scene folder.

The reported H100 run (9 objects, approximately 25.2 MiB scene GLB) comes from the
user's prior execution record. This separation does not rerun that GPU job or
independently certify its files. See `SOURCE_AUDIT.md` for source-level findings.

Subsequent real acceptance was executed on 2026-09-12 after the separation.
See [ACCEPTANCE.md](ACCEPTANCE.md): the new run completed with 9 objects, and the
actual allocated GPU was H200/sm90 despite the H100 request. Visual limitations
are recorded separately from execution success.
