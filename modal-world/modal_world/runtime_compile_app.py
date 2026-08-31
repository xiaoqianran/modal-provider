from __future__ import annotations

import json

import modal

from .hyworld2_runtime import HYWORLD2_REVISION, hyworld2_worldgen_stage1_image
from .runtime_compile import build_runtime_world_manifest
from .worldgen_job import (
    build_stage_manifest,
    fingerprint_files,
    manifest_matches,
    resolve_worldgen_job_root,
    write_stage_manifest,
)

app = modal.App("modal-world-runtime-compile")
worldgen_outputs = modal.Volume.from_name("hyworld2-worldgen-output", create_if_missing=True)


@app.function(
    image=hyworld2_worldgen_stage1_image,
    cpu=8.0,
    memory=32768,
    volumes={"/worldgen": worldgen_outputs},
    timeout=30 * 60,
)
def compile_world_runtime(
    job_id: str = "case000",
    target_triangles: int = 100_000,
    force: bool = False,
) -> dict:
    """Compile HYWorld's dense Stage 1 mesh into a browser/runtime-friendly world mesh."""
    import time

    import numpy as np
    import open3d as o3d

    if target_triangles < 10_000:
        raise ValueError("target_triangles must be >= 10000")

    worldgen_outputs.reload()
    target = resolve_worldgen_job_root(job_id)
    source_mesh = target / "render_results/global_mesh.ply"
    if not source_mesh.is_file():
        raise RuntimeError(f"runtime compile source mesh missing: {source_mesh}")

    runtime_dir = target / "runtime"
    runtime_mesh = runtime_dir / "environment.ply"
    runtime_manifest = runtime_dir / "world.json"
    compile_manifest = build_stage_manifest(
        job_id=job_id,
        stage="runtime-compile",
        hyworld_revision=HYWORLD2_REVISION,
        input_fingerprint=fingerprint_files([source_mesh], root=target),
        config={
            "profile": "agentscape-environment-v1",
            "target_triangles": int(target_triangles),
            "coordinate_system": "z-up",
        },
    )
    if (
        not force
        and runtime_mesh.is_file()
        and runtime_manifest.is_file()
        and manifest_matches(target, "runtime-compile", compile_manifest)
    ):
        payload = json.loads(runtime_manifest.read_text())
        return {
            "resumed": True,
            "runtime_dir": str(runtime_dir),
            "runtime_mesh": str(runtime_mesh),
            "runtime_manifest": str(runtime_manifest),
            **payload["mesh"],
        }

    started = time.perf_counter()
    mesh = o3d.io.read_triangle_mesh(str(source_mesh), enable_post_processing=False)
    source_vertices = len(mesh.vertices)
    source_triangles = len(mesh.triangles)
    if source_vertices < 3 or source_triangles < 1:
        raise RuntimeError("runtime compile source mesh is empty")

    source_min = np.asarray(mesh.get_min_bound(), dtype=np.float64)
    source_max = np.asarray(mesh.get_max_bound(), dtype=np.float64)
    if not np.isfinite(source_min).all() or not np.isfinite(source_max).all():
        raise RuntimeError("runtime compile source mesh has non-finite bounds")

    if source_triangles > target_triangles:
        mesh = mesh.simplify_quadric_decimation(target_number_of_triangles=target_triangles)
    runtime_vertices = len(mesh.vertices)
    runtime_triangles = len(mesh.triangles)
    if runtime_vertices < 3 or runtime_triangles < 1:
        raise RuntimeError("runtime mesh simplification produced an empty mesh")
    if runtime_triangles > source_triangles:
        raise RuntimeError("runtime mesh simplification increased triangle count")

    mesh.compute_vertex_normals()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if not o3d.io.write_triangle_mesh(str(runtime_mesh), mesh, write_ascii=False):
        raise RuntimeError(f"failed to write runtime mesh: {runtime_mesh}")

    visual_path = target / "gs_result/ply/point_cloud_7999.spz"
    semantics_path = target / "objects.json"
    navmesh_metadata_path = target / "navmesh/metadata.json"
    payload = build_runtime_world_manifest(
        job_id=job_id,
        source_mesh="../render_results/global_mesh.ply",
        runtime_mesh="environment.ply",
        source_vertices=source_vertices,
        source_triangles=source_triangles,
        runtime_vertices=runtime_vertices,
        runtime_triangles=runtime_triangles,
        source_min_bound=source_min.tolist(),
        source_max_bound=source_max.tolist(),
        visual="../gs_result/ply/point_cloud_7999.spz" if visual_path.is_file() else None,
        semantics="../objects.json" if semantics_path.is_file() else None,
        navmesh_metadata=("../navmesh/metadata.json" if navmesh_metadata_path.is_file() else None),
    )
    payload["compiler"] = {
        "hyworldRevision": HYWORLD2_REVISION,
        "profile": "agentscape-environment-v1",
        "elapsedS": round(time.perf_counter() - started, 3),
    }
    runtime_manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    write_stage_manifest(target, "runtime-compile", compile_manifest)
    worldgen_outputs.commit()

    return {
        "resumed": False,
        "runtime_dir": str(runtime_dir),
        "runtime_mesh": str(runtime_mesh),
        "runtime_manifest": str(runtime_manifest),
        "runtime_mesh_bytes": runtime_mesh.stat().st_size,
        **payload["mesh"],
        **payload["compiler"],
    }
