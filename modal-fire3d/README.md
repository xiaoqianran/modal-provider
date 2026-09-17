# modal-fire3d

Latest real-run evidence: [2026-09-12 acceptance](ACCEPTANCE.md).

Wall-loss diagnosis and actual H100 repair: [background fix](BACKGROUND_FIX.md).
The backend now defaults to an observed-background policy for `single_image`;
use `options.background_policy="official"` for exact upstream settings.
The official smoke entry point retains its official default; corrected full runs
require `background_policy="observed_single_image"` and a fresh `run_id`.

Independent FIRE3D reconstruction package. HYWorld2 generation and reconstruction
remain in `../modal-world`. Native wheel builders remain in
`../modal-build/integrations/fire3d`.

| Boundary | FIRE3D | HYWorld2 |
| --- | --- | --- |
| Python package | `modal_fire3d` | `modal_world` |
| Service | `modal_fire3d.service.execute` | `modal_world.service.execute` |
| Deployment metadata | `modal_fire3d.deployment` | `modal_world.deployment` |
| Modal entry point | `modal_fire3d.app` | `modal_world.app` and stage workers |
| Remote app | `modal-world-fire3d` (retained) | `modal-world` and stage workers |
| Outputs | composed scene and canonical object GLBs | existing HYWorld2 artifacts |
| Data/models/output volumes | `fire3d-data`, `fire3d-models`, `fire3d-output` | HYWorld2 volumes |

FIRE3D now supports two reconstruction inputs:

- `prepared_dataset`: the original release-compatible path remains unchanged.
- JPG/PNG: `modal_fire3d.pi3_preprocessor` runs the paper's pinned Pi3 path, preserves
  the dense point map, and materializes the exact `single_image` contract before the
  normal FIRE3D pipeline runs.

The raw-image adapter writes `rgb.jpeg`, ordered `aligned_pcd.ply`, `camera.json`,
`preprocess.json`, and `single_image_valid.txt`. The PLY always has exactly
`floor(H/2)*floor(W/2)` vertices; low-confidence and geometry-edge samples remain in
that ordered lattice as NaN instead of being deleted. Pi3 is released before the
FIRE3D subprocess starts so its 1B model does not reserve H100 VRAM during the larger
reconstruction stages.

`uv sync --extra dev` installs the sibling `modal-world` package only to share its
lightweight backend/result contracts. FIRE3D does not import HYWorld2 adapters,
workers, deployment metadata, or runtime. Its revision hashes only its own Python
sources and the two shared contract modules.

```powershell
uv run pytest -q
uv run modal deploy -m modal_fire3d.app
uv run modal run -m modal_fire3d.app::preload_raw_image_models
uv run modal run -m modal_fire3d.app::raw_image --image path/to/input.png
uv run modal run -m modal_fire3d.app::official_single_image_smoke
```

The old `modal_world.fire3d_app` and `modal_world.backends.fire3d` imports have moved;
update scripts to the entry points above. No compatibility alias or automatic
cross-registration is installed. This package does not yet provide the
AgentScape-facing `modal_gen.providers` plugin.

See [reproduction instructions](FIRE3D_REPRO.md) and
[source audit and preprocessing decisions](SOURCE_AUDIT.md).

For a fresh deployed H100 acceptance run with downloaded GLB validation:

```powershell
$env:PYTHONUTF8 = "1"
uv run --isolated modal deploy -m modal_fire3d.app
uv run --isolated --with trimesh --with numpy --with pillow python scripts/acceptance.py
```

Evidence is written under `acceptance/<UTC-run-id>/` (excluded from Git). Each run
uses a new remote directory, saves the exact CLI/exit code/full logs, and downloads
the scene and every canonical object GLB for structural and geometry checks.
