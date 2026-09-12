"""Measure observed background support and compose a background-only replacement."""

import json
import sys
from pathlib import Path

import numpy as np
import trimesh

baseline = Path("acceptance/20260911T204708Z")
candidate = Path(sys.argv[1])
suffix = "output/reconstruction/003025/appearance/predicted_textured_world_scene.glb"
old = trimesh.load(baseline / suffix, force="scene", process=False)
new = trimesh.load(candidate / suffix, force="scene", process=False)
assert len(new.graph.nodes_geometry) == 1
old_node = "background_position_0000"
old_transform, old_geom = old.graph[old_node]
new_transform, new_geom = new.graph[new.graph.nodes_geometry[0]]
old_mesh = old.geometry[old_geom].copy().apply_transform(old_transform)
new_mesh = new.geometry[new_geom].copy().apply_transform(new_transform)
condition = np.load(next((candidate / "output").rglob("background_condition.npz")))
points = trimesh.transform_points(condition["points"], np.linalg.inv(condition["norm_transform"]))
# Evaluate a deterministic subset, with exact point-to-triangle distances.
query = points[::4]
comparison = {}
for name, mesh in (("official", old_mesh), ("no_room_filter", new_mesh)):
    distances = []
    for start in range(0, len(query), 256):
        distances.extend(trimesh.proximity.closest_point(mesh, query[start:start+256])[1])
    distances = np.asarray(distances)
    comparison[name] = {
        "median_m": float(np.median(distances)), "p95_m": float(np.quantile(distances, .95)),
        "coverage_5cm": float(np.mean(distances < .05)),
        "coverage_10cm": float(np.mean(distances < .10)),
        "faces": len(mesh.faces),
    }
comparison["num_query_points"] = len(query)
comparison["canonical_outside_unit_box"] = int(np.any(np.abs(condition["canonical"]) > .5, axis=1).sum())
comparison["canonical_count"] = len(condition["canonical"])
old.delete_geometry(old_geom)
old.add_geometry(new.geometry[new_geom], node_name=old_node, geom_name=old_geom, transform=new_transform)
output = candidate / "repaired_scene.glb"
old.export(output)
reloaded = trimesh.load(output, force="scene", process=False)
source = trimesh.load(baseline / suffix, force="scene", process=False)
for node in source.graph.nodes_geometry:
    if node == old_node:
        continue
    before_transform, before_name = source.graph[node]
    after_transform, after_name = reloaded.graph[node]
    before, after = source.geometry[before_name], reloaded.geometry[after_name]
    np.testing.assert_array_equal(before.vertices, after.vertices)
    np.testing.assert_array_equal(before.faces, after.faces)
    np.testing.assert_allclose(before_transform, after_transform, atol=1e-12)
    np.testing.assert_array_equal(before.visual.uv, after.visual.uv)
    np.testing.assert_array_equal(np.asarray(before.visual.material.baseColorTexture),
                                  np.asarray(after.visual.material.baseColorTexture))
comparison["foreground_unchanged"] = True
(candidate / "background_comparison.json").write_text(json.dumps(comparison, indent=2))
print(json.dumps(comparison, indent=2))
