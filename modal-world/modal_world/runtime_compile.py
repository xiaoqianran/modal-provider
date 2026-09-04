from __future__ import annotations

import math
from itertools import pairwise
from typing import Any


def runtime_layout_from_z_up_bounds(
    min_bound: list[float] | tuple[float, float, float],
    max_bound: list[float] | tuple[float, float, float],
) -> dict[str, Any]:
    """Convert HYWorld Z-up bounds to AgentScape Y-up horizontal layout bounds."""
    if len(min_bound) != 3 or len(max_bound) != 3:
        raise ValueError("world bounds must contain exactly three coordinates")
    values = [*min_bound, *max_bound]
    if not all(isinstance(value, (int, float)) for value in values):
        raise TypeError("world bounds must be numeric")

    min_x, min_y, min_z = map(float, min_bound)
    max_x, max_y, max_z = map(float, max_bound)
    if min_x > max_x or min_y > max_y or min_z > max_z:
        raise ValueError("world bounds min must not exceed max")

    # AgentScape uses the same transform as loadGeneratedWorld(z-up):
    # rotationX(-pi/2): (x, y, z) -> (x, z, -y).
    return {
        "bounds": {
            "min": [min_x, -max_y],
            "max": [max_x, -min_y],
        },
        "vertical": {"min": min_z, "max": max_z},
        "groundY": 0.0,
        "margin": 0.5,
    }



def navigation_corridor_mesh(
    paths: list[list[list[float]]],
    *,
    half_width: float = 0.45,
) -> tuple[list[list[float]], list[list[int]]]:
    """Build a lightweight Z-up triangle corridor from HYWorld's verified walk paths.

    This mesh is navigation-only: it is intentionally independent from the noisy
    reconstruction mesh used for rendering fallback and physics collision.
    """
    import math

    if not math.isfinite(half_width) or half_width <= 0:
        raise ValueError("navigation half_width must be positive")
    vertices: list[list[float]] = []
    triangles: list[list[int]] = []
    for path in paths:
        if not isinstance(path, list) or len(path) < 2:
            continue
        for start, end in pairwise(path):
            if len(start) != 3 or len(end) != 3:
                continue
            x0, y0, z0 = map(float, start)
            x1, y1, z1 = map(float, end)
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if not math.isfinite(length) or length < 1e-4:
                continue
            lx, ly = -dy / length * half_width, dx / length * half_width
            base = len(vertices)
            vertices.extend([
                [x0 + lx, y0 + ly, z0],
                [x0 - lx, y0 - ly, z0],
                [x1 + lx, y1 + ly, z1],
                [x1 - lx, y1 - ly, z1],
            ])
            # Counter-clockwise in HYWorld Z-up coordinates => +Z normal.
            triangles.extend([[base, base + 1, base + 2], [base + 1, base + 3, base + 2]])
    if not triangles:
        raise ValueError("navigation paths produced no corridor triangles")
    return vertices, triangles


def load_navigation_paths(root: Any) -> list[list[list[float]]]:
    import json

    paths: list[list[list[float]]] = []
    for name in ("exploration", "target", "surround", "reconstruct"):
        path = root / "navmesh" / name / "paths.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text())
        if isinstance(payload, list):
            paths.extend(item for item in payload if isinstance(item, list))
    return paths



def build_runtime_semantics(labels: object, *, source: str = "../objects.json") -> dict[str, Any]:
    if not isinstance(labels, list):
        raise TypeError("runtime semantics source must be a list")
    categories: list[str] = []
    instances: list[dict[str, Any]] = []
    seen_categories: set[str] = set()
    seen_instances: set[str] = set()

    def add_category(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        label = value.strip()
        if not label:
            return None
        key = label.casefold()
        if key not in seen_categories:
            seen_categories.add(key)
            categories.append(label)
        return label

    def finite_vec3(value: object) -> bool:
        return (
            isinstance(value, list)
            and len(value) == 3
            and all(isinstance(item, (int, float)) and math.isfinite(item) for item in value)
        )

    for item in labels:
        if isinstance(item, str):
            add_category(item)
            continue
        if not isinstance(item, dict):
            continue
        instance_id = str(item.get("id", "")).strip()
        label = add_category(item.get("label"))
        bbox = item.get("bbox")
        if (
            not instance_id
            or not label
            or instance_id in seen_instances
            or not finite_vec3(item.get("center"))
            or not isinstance(bbox, dict)
            or not finite_vec3(bbox.get("min"))
            or not finite_vec3(bbox.get("max"))
        ):
            continue
        seen_instances.add(instance_id)
        instance = {
            "id": instance_id,
            "label": label,
            "center": list(item["center"]),
            "bbox": {"min": list(bbox["min"]), "max": list(bbox["max"])},
        }
        confidence = item.get("confidence")
        if isinstance(confidence, (int, float)) and math.isfinite(confidence):
            instance["confidence"] = float(confidence)
        instances.append(instance)

    return {
        "schemaVersion": 1,
        "granularity": "instance" if instances else "category",
        "categories": categories,
        "instances": instances,
        "provenance": {
            "source": source,
            "kind": "provider-instance-evidence" if instances else "hyworld2-object-labels",
        },
    }

def build_runtime_world_manifest(
    *,
    job_id: str,
    source_mesh: str,
    runtime_mesh: str,
    source_vertices: int,
    source_triangles: int,
    runtime_vertices: int,
    runtime_triangles: int,
    source_min_bound: list[float],
    source_max_bound: list[float],
    visual: str | None = None,
    semantics: str | None = None,
    navigation: str | None = None,
    navmesh_metadata: str | None = None,
) -> dict[str, Any]:
    if not job_id:
        raise ValueError("job_id must not be empty")
    if min(source_vertices, source_triangles, runtime_vertices, runtime_triangles) <= 0:
        raise ValueError("runtime world mesh counts must be positive")
    if runtime_triangles > source_triangles:
        raise ValueError("runtime mesh must not contain more triangles than its source")

    artifacts: dict[str, Any] = {
        "environment": {
            "path": runtime_mesh,
            "format": "ply",
            "role": "world-geometry",
        }
    }
    if visual:
        artifacts["visual"] = {
            "path": visual,
            "format": visual.rsplit(".", 1)[-1].lower(),
            "role": "world-visual",
        }
    if semantics:
        artifacts["semantics"] = {
            "path": semantics,
            "format": "json",
            "role": "world-semantics",
        }
    if navigation:
        artifacts["navigation"] = {
            "path": navigation,
            "format": navigation.rsplit(".", 1)[-1].lower(),
            "role": "world-navigation",
            "runtimeMode": "dedicated-geometry",
        }
    if navmesh_metadata:
        artifacts["navigationMetadata"] = {
            "path": navmesh_metadata,
            "format": "json",
            "role": "world-navigation-metadata",
        }

    return {
        "schemaVersion": 1,
        "id": job_id,
        "coordinateSystem": "z-up",
        "metersPerUnit": 1.0,
        "artifacts": artifacts,
        "layout": runtime_layout_from_z_up_bounds(source_min_bound, source_max_bound),
        "mesh": {
            "source": source_mesh,
            "sourceVertices": source_vertices,
            "sourceTriangles": source_triangles,
            "runtimeVertices": runtime_vertices,
            "runtimeTriangles": runtime_triangles,
            "triangleReduction": round(1.0 - runtime_triangles / source_triangles, 6),
        },
    }
