"""Real geometry integration tests; run in the isolated .venv-mesh environment."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from modal_3d.operation_runner import run_operation_job
from modal_3d.operations import digest_file

pytestmark = pytest.mark.skipif(importlib.util.find_spec("bpy") is None, reason="requires bpy 4.2 runtime")


class Volume:
    def reload(self):
        pass

    def commit(self):
        pass


def descriptor(root, path):
    return {"path": path.relative_to(root).as_posix(), "mime": "model/gltf-binary",
            "bytes": path.stat().st_size, "sha256": digest_file(path)}


def test_real_processing_pipeline(tmp_path):
    source = tmp_path / "source.glb"
    made = subprocess.run([sys.executable, str(Path(__file__).with_name("mesh_fixture.py")), str(source)],
                          capture_output=True, text=True, check=False)
    assert made.returncode == 0, made.stderr
    initial = descriptor(tmp_path, source)
    results = {}
    for operation, options in [("inspect_mesh", {}), ("mesh_cleanup", {}), ("mesh_repair", {}),
                               ("decimate", {"target_faces": 300}), ("retopology", {"target_faces": 100})]:
        result = run_operation_job(Volume(), operation, {"asset": initial}, options, root=tmp_path)
        results[operation] = result
        assert result["metrics"]["after"]["triangles"] > 0
        assert all((tmp_path / a["path"]).is_file() for a in result["artifacts"])
    inspected = results["inspect_mesh"]["metrics"]["after"]
    assert inspected["components"] == 1
    assert inspected["boundary_edges"] == 0
    assert inspected["nonmanifold_edges"] == 0
    assert inspected["serialized_boundary_edges"] > 0
    assert inspected["geometric_vertices"] < inspected["vertices"]
    assert results["decimate"]["metrics"]["after"]["triangles"] < 960
    assert results["decimate"]["metrics"]["after"]["components"] == 1
    assert results["decimate"]["metrics"]["after"]["boundary_edges"] == 0
    assert results["decimate"]["metrics"]["after"]["nonmanifold_edges"] == 0

    # A target above the source face count must be a true semantic no-op:
    # preserve seams/UV/material state instead of welding or touching topology.
    noop = run_operation_job(
        Volume(), "decimate", {"asset": initial}, {"target_faces": 20000}, root=tmp_path
    )
    assert noop["metrics"]["skipped"] is True
    assert noop["metrics"]["skip_reason"] == "target_not_lower_than_source"
    assert noop["metrics"]["topology_changed"] is False
    assert noop["metrics"]["before"] == noop["metrics"]["after"]
    assert noop["metrics"]["achieved_faces"] == inspected["triangles"]
    assert noop["metrics"]["after"]["serialized_boundary_edges"] == inspected["serialized_boundary_edges"]
    assert noop["metrics"]["after"]["uv"] == inspected["uv"]
    assert noop["metrics"]["after"]["materials"] == inspected["materials"]

    noop_asset = next(a for a in noop["artifacts"] if a["role"] == "primary-glb")
    assert noop_asset["sha256"] == initial["sha256"]
    assert noop_asset["bytes"] == initial["bytes"]
    assert (tmp_path / noop_asset["path"]).read_bytes() == source.read_bytes()
    noop_reloaded = run_operation_job(
        Volume(), "inspect_mesh", {"asset": noop_asset}, {}, root=tmp_path
    )["metrics"]["after"]
    assert noop_reloaded["components"] == inspected["components"]
    assert noop_reloaded["boundary_edges"] == inspected["boundary_edges"]
    assert noop_reloaded["nonmanifold_edges"] == inspected["nonmanifold_edges"]
    assert noop_reloaded["uv"] == inspected["uv"]
    assert noop_reloaded["materials"] == inspected["materials"]

    assert results["retopology"]["metrics"]["after"]["quad_ratio"] > 0.9
    quad_obj = next(a for a in results["retopology"]["artifacts"] if a["role"] == "editable-source")
    face_lines = [l for l in (tmp_path / quad_obj["path"]).read_text().splitlines() if l.startswith("f ")]
    assert any(len(l.split()) == 5 for l in face_lines)
    target = results["decimate"]["artifacts"][0]
    uv = run_operation_job(Volume(), "uv_unwrap", {"asset": target}, {"resolution": 128, "padding": 2}, root=tmp_path)
    assert uv["metrics"]["before"]["components"] == 1
    assert uv["metrics"]["before"]["boundary_edges"] == 0
    assert uv["metrics"]["before"]["nonmanifold_edges"] == 0
    source_bounds = np.asarray(results["inspect_mesh"]["metrics"]["before"]["bounds"])
    reloaded_bounds = np.asarray(uv["metrics"]["before"]["bounds"])
    assert np.allclose(source_bounds, reloaded_bounds, atol=0.05)
    assert uv["metrics"]["after"]["uv"][0]["finite"]
    assert uv["metrics"]["uv_atlases"][0]["utilization"] > 0
    baked = run_operation_job(Volume(), "texture_bake", {"source": initial, "target": uv["artifacts"][0]},
                             {"resolution": 128, "padding": 2, "ray_distance": 0.2}, root=tmp_path)
    assert not baked["metrics"]["topology_changed"]
    assert len([a for a in baked["artifacts"] if a["mime"] == "image/png"]) == 4
    from PIL import Image
    color = next(a for a in baked["artifacts"] if a["role"].endswith("baseColor"))
    pixels = np.asarray(Image.open(tmp_path / color["path"]))
    assert pixels[..., :3].std() > 10
    assert pixels[..., 3].max() > 200
    repeat = run_operation_job(Volume(), "decimate", {"asset": initial}, {"target_faces": 300}, root=tmp_path)
    assert repeat["cache_hit"]
    (tmp_path / "evidence.json").write_text(json.dumps({k: v["metrics"] for k, v in results.items()}, indent=2))
