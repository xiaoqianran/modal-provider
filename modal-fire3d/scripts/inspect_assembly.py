"""Verify exported world-node transforms against the upstream appearance manifest."""

import json
import sys
from pathlib import Path

import numpy as np
import trimesh

root = Path(sys.argv[1])
appearance = root / "output/reconstruction/003025/appearance"
summary = json.loads((appearance / "appearance_summary.json").read_text())
scene = trimesh.load(appearance / "predicted_textured_world_scene.glb", force="scene", process=False)
objects = summary["composed_world_scene"]["objects"]
assert len(objects) == len(scene.graph.nodes_geometry)
reports = []
for item in objects:
    transform, geometry = scene.graph[item["node_name"]]
    expected = np.asarray(item["object_to_world"])
    np.testing.assert_allclose(transform, expected, rtol=1e-6, atol=1e-6)
    assert np.isfinite(transform).all() and abs(np.linalg.det(transform[:3, :3])) > 1e-10
    mesh = scene.geometry[geometry]
    assert len(mesh.faces) == item["faces"]
    assert len(mesh.vertices) == item["vertices"]
    assert np.isfinite(mesh.visual.uv).all()
    reports.append({
        "node": item["node_name"],
        "transform_max_abs_error": float(np.max(np.abs(transform - expected))),
        "faces": len(mesh.faces), "vertices": len(mesh.vertices),
        "uv_finite": True,
    })
(root / "assembly_validation.json").write_text(json.dumps(reports, indent=2) + "\n")
print(json.dumps({"validated_nodes": len(reports), "faces": sum(r["faces"] for r in reports)}))
