"""Audit which observed surfaces the frozen minimum-area room-box filter rejected."""

import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

root = Path("acceptance/bg-no-room-filter-v1")
data = np.load(root / "background_condition.npz")
audit = json.loads(Path("acceptance/20260911T204708Z/output/reconstruction/003025/input_audit.json").read_text())
prior = audit["background_room_box_prior"]
box = prior["box"]
points = data["points"]
local = (points - box["center"]) @ np.asarray(box["rotation_box_to_scene"])
delta = np.abs(local) - box["half_extents"]
distances = np.linalg.norm(np.maximum(delta, 0), axis=1)
inside = np.all(delta <= 0, axis=1)
distances[inside] = np.min(-delta[inside], axis=1)
keep = distances <= prior["effective_distance_threshold"] + 1e-12
assert keep.sum() == prior["retained_background_points"]
grid = data["all_points"].reshape(120, 160, 3)
normal = np.cross(np.gradient(grid, axis=1), np.gradient(grid, axis=0))
length = np.linalg.norm(normal, axis=-1)
normal /= np.maximum(length[..., None], 1e-9)
_, indices = cKDTree(data["all_points"]).query(points)
normal_z = np.abs(normal.reshape(-1, 3)[indices, 2])
valid = length.ravel()[indices] > 1e-9
result = {}
for name, mask in (("all_background", np.ones(len(points), bool)),
                   ("vertical_surfaces", valid & (normal_z < .35)),
                   ("horizontal_surfaces", valid & (normal_z > .85))):
    result[name] = {"input": int(mask.sum()), "retained": int((mask & keep).sum()),
                    "rejected": int((mask & ~keep).sum())}
(root / "filter_audit.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
