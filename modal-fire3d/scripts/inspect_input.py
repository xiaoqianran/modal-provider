"""Read the actual official PLY and check its grid/camera correspondence."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

root = Path(sys.argv[1])
width, height = Image.open(root / "input.jpeg").size
raw = (root / "aligned_pcd.ply").read_bytes()
header = raw[:raw.index(b"end_header") + len(b"end_header")].decode("ascii")
points = np.asarray(trimesh.load(root / "aligned_pcd.ply", process=False).vertices)
assert points.shape == ((height // 2) * (width // 2), 3)
valid = np.isfinite(points).all(axis=1)
camera = json.loads((root / "camera.json").read_text())["native"]
eye = np.asarray(camera["frame"]["eye"])
forward = np.asarray(camera["forward"])
up = np.asarray(camera["frame"]["up"])
right = np.cross(forward, up)
relative = points[valid] - eye
x, y, z = relative @ right, relative @ -up, relative @ forward
K = np.asarray(camera["K"])
u, v = x / z * K[0, 0] + K[0, 2], y / z * K[1, 1] + K[1, 2]
grid_y, grid_x = np.indices((height // 2, width // 2))
errors = {}
for offset in (0.0, 0.5, 1.0):
    error = np.hypot(u - (grid_x.ravel()[valid]*2 + offset), v - (grid_y.ravel()[valid]*2 + offset))
    errors[str(offset)] = {"median_px": float(np.median(error)), "p95_px": float(np.quantile(error, .95))}
report = {
    "rgb_size": [width, height], "grid_size": [height//2, width//2],
    "point_count": len(points), "finite_points": int(valid.sum()),
    "ply_header": header, "points_sha256": hashlib.sha256(raw).hexdigest(),
    "positive_camera_depth_fraction": float(np.mean(z > 0)),
    "reprojection_by_pixel_offset": errors,
}
(root / "input_validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
