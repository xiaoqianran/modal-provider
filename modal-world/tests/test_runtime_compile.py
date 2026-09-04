from pathlib import Path

from modal_world.runtime_compile import (
    build_runtime_world_manifest,
    navigation_corridor_mesh,
    runtime_layout_from_z_up_bounds,
)


def test_runtime_layout_matches_agentscape_z_up_transform():
    layout = runtime_layout_from_z_up_bounds(
        [-5.0, -4.0, -0.25],
        [6.0, 7.0, 8.0],
    )
    assert layout == {
        "bounds": {"min": [-5.0, -7.0], "max": [6.0, 4.0]},
        "vertical": {"min": -0.25, "max": 8.0},
        "groundY": 0.0,
        "margin": 0.5,
    }


def test_runtime_manifest_separates_visual_geometry_semantics_and_navigation():
    manifest = build_runtime_world_manifest(
        job_id="garden-v1",
        source_mesh="../render_results/global_mesh.ply",
        runtime_mesh="environment.ply",
        source_vertices=460_800,
        source_triangles=744_212,
        runtime_vertices=61_000,
        runtime_triangles=100_000,
        source_min_bound=[-5.98, -5.03, -0.35],
        source_max_bound=[5.64, 5.93, 5.99],
        visual="../gs_result/ply/point_cloud_7999.spz",
        navigation="navigation.ply",
        semantics="semantics.json",
        navmesh_metadata="../navmesh/metadata.json",
    )
    assert manifest["schemaVersion"] == 1
    assert manifest["coordinateSystem"] == "z-up"
    assert manifest["artifacts"]["environment"]["role"] == "world-geometry"
    assert manifest["artifacts"]["visual"]["role"] == "world-visual"
    assert manifest["artifacts"]["semantics"]["role"] == "world-semantics"
    assert manifest["artifacts"]["semantics"]["path"] == "semantics.json"
    assert manifest["artifacts"]["navigation"]["runtimeMode"] == "dedicated-geometry"
    assert manifest["artifacts"]["navigation"]["path"] == "navigation.ply"
    assert manifest["artifacts"]["navigationMetadata"]["role"] == "world-navigation-metadata"
    assert manifest["mesh"]["runtimeTriangles"] == 100_000
    assert manifest["mesh"]["triangleReduction"] > 0.8


def test_runtime_compiler_is_cpu_only_and_isolated_from_main_app():
    source = Path("modal_world/runtime_compile_app.py").read_text()
    assert 'app = modal.App("modal-world-runtime-compile")' in source
    assert "gpu=" not in source
    assert 'target / "render_results/global_mesh.ply"' in source
    assert "simplify_quadric_decimation" in source
    assert 'stage="runtime-compile"' in source
    assert 'target / "runtime"' in source
    assert 'runtime_dir / "environment.ply"' in source
    assert 'runtime_dir / "world.json"' in source
    assert 'target / "objects.json"' in source
    assert 'target / "gs_result/ply/point_cloud_7999.spz"' in source
    assert "fingerprint_inputs.append(optional_input)" in source
    assert "semantics_path.is_file() == runtime_semantics.is_file()" in source
    assert "has_dedicated_navigation == runtime_navigation.is_file()" in source
    assert "worldgen_outputs.commit()" in source


def test_navigation_corridor_mesh_builds_upward_z_up_quads():
    vertices, triangles = navigation_corridor_mesh([[[0, 0, 0], [2, 0, 0]]], half_width=0.5)
    assert vertices == [[0.0, 0.5, 0.0], [0.0, -0.5, 0.0], [2.0, 0.5, 0.0], [2.0, -0.5, 0.0]]
    assert triangles == [[0, 1, 2], [1, 3, 2]]


def test_navigation_corridor_mesh_rejects_empty_paths():
    import pytest
    with pytest.raises(ValueError, match="no corridor triangles"):
        navigation_corridor_mesh([])
