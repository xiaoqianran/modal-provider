# Background-wall repair — 2026-09-12

## Diagnosis

The missing walls in official sample `single_image/003025` are real geometry loss,
visible with both double-sided PBR and unlit rendering. The scene export includes
its background object; this is not simply backface culling or Blender exposure.

At pinned upstream commit `2368dd2f3909120cf90bbf8a17807abe9c41e600`,
`utils/background_room_box.py` fits a minimum-area XY room rectangle and filters
background observations by distance to its shell. For this partial single view,
the fitted yaw is 73 degrees and does not follow the observed wall surfaces.
Only 3,862 of 12,515 background points survive the 12 cm shell filter.
Of 10,695 points with approximately vertical-surface normals, 8,358 are rejected.
Unit-box clipping affects only 27 points, so it does not explain the large holes.

## Real GPU validation and delivered scene

Original full run: `20260911T204708Z`. Repair: `bg-no-room-filter-v1`.
Modal call: `fc-01M2AQGKSPR1ESGDEECKC8MQK9`, actual NVIDIA H100 80 GB,
exit code 0, approximately 369 seconds. Reused the original perception outputs;
ran the official neural reconstruction and texturing for background only with
`--no-background-room-box-prior`. No hand-built wall planes were inserted.

The repaired background was assembled with the eight original foreground objects.
After GLB round-trip, foreground vertices, faces, UVs and base-color textures are
array-identical; node transforms agree within tolerance. Original artifacts remain
untouched. This is a background-only repair, not a fresh full nine-object run.

Exact point-to-triangle distances for a deterministic 3,129-point subset of the
input background, transformed back to dataset world coordinates:

| Metric | Official | Repaired |
| --- | ---: | ---: |
| Median distance | 25.01 cm | 1.58 cm |
| 95th percentile distance | 94.00 cm | 6.02 cm |
| Input points within 10 cm of mesh | 39.95% | 99.52% |

These measure agreement with observed input geometry, **not** ground-truth room
completion or accuracy behind occlusions. The meter labels use dataset units.

Local artifacts (acceptance directory is excluded from Git):

- [Repaired full scene](acceptance/bg-no-room-filter-v1/repaired_scene.glb)
- [Same-camera preview](acceptance/bg-no-room-filter-v1/repaired-preview.png)
- [Comparison metrics](acceptance/bg-no-room-filter-v1/background_comparison.json)
- [Filter audit](acceptance/bg-no-room-filter-v1/filter_audit.json)
- [Execution and download record](acceptance/bg-no-room-filter-v1/result.json)

## Integration and boundaries

`Fire3DBackend` defaults to `options.background_policy="observed_single_image"`
for the single-image dataset, retaining observed background conditioning.
Other datasets remain official. `options.background_policy="official"` restores
the unchanged upstream behavior. Repair requires a fresh output directory to
avoid silently reusing a previously filtered reconstruction.

The policy writes a separate, explicitly named JSON protocol with parent SHA256;
only `reconstruction.background.room_box_prior` changes among runtime settings.
No upstream source, dependency stack, foreground model or HYWorld2 code is changed.
This is a local correction, **not** an exact official-protocol reproduction.

The remote `official_single_image_smoke` retains its official default. To explicitly
run a full corrected reconstruction, pass `background_policy="observed_single_image"`
and a fresh `run_id`. The independent `modal_fire3d.background_app` plus
`scripts/background_ablation.py` reproduces the cheaper background-only experiment.

## Remaining limitations

Major observed wall surfaces are restored. Background textures remain noisy and
some furniture-shaped background patches persist; the repaired mesh is not a
clean CAD room shell. Disabling filtering can retain incorrect background labels.
Only this official sample has been validated, so quality on arbitrary images is
not established. Unobserved walls cannot be certified from a single view.

Preview uses the existing Three.js setup, not an official Blender render. Blender
color-management/lighting differences were not corrected by this geometry change.
