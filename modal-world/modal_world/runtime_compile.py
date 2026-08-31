from __future__ import annotations

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
    if navmesh_metadata:
        artifacts["navigation"] = {
            "path": navmesh_metadata,
            "format": "json",
            "role": "world-navigation-metadata",
            "runtimeMode": "rebuild-from-environment-mesh",
        }

    return {
        "schemaVersion": 1,
        "id": job_id,
        "coordinateSystem": "z-up",
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
