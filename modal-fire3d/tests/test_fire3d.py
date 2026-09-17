from __future__ import annotations

import json
from pathlib import Path

import pytest
from modal_world.backend import BackendUnavailable
from modal_world.contracts import Operation, WorldRequest

from modal_fire3d.backend import FIRE3D_REVISION, Fire3DBackend


def test_fire3d_capability_is_reconstruction_only_and_truthful():
    capability = Fire3DBackend().capability
    assert capability.backend == "fire3d"
    assert capability.operations == frozenset({Operation.RECONSTRUCT})
    assert "prepared_dataset" in capability.inputs
    assert "image/jpeg" in capability.inputs
    assert "image/png" in capability.inputs
    assert "world_scene_glb" in capability.outputs
    assert any("aligned RGB + point-cloud" in note for note in capability.notes)


def test_fire3d_requires_pinned_checkout(tmp_path: Path):
    source = tmp_path / "data"
    source.mkdir()
    request = WorldRequest(
        operation=Operation.RECONSTRUCT,
        input_path=source,
        output_dir=tmp_path / "out",
        options={},
    )
    with pytest.raises(BackendUnavailable):
        Fire3DBackend().run(request)


def test_fire3d_discovers_composed_scene_and_individual_objects(tmp_path: Path):
    scene_id = "003025"
    recon = tmp_path / "reconstruction" / scene_id
    (recon / "appearance/objects/0001").mkdir(parents=True)
    (recon / "appearance/predicted_textured_world_scene.glb").write_bytes(b"glb")
    (recon / "appearance/objects/0001/canonical.glb").write_bytes(b"obj")
    (recon / "appearance/appearance_summary.json").write_text("{}", encoding="utf-8")
    (recon / "inference_summary.json").write_text(
        json.dumps({"status": "complete", "num_decoded_objects": 1, "num_expected_objects": 1}),
        encoding="utf-8",
    )
    (tmp_path / "summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "resolved_protocol.json").write_text("{}", encoding="utf-8")
    perception = tmp_path / "perception/single_image/val_0"
    perception.mkdir(parents=True)
    (perception / "oriented_bboxes.json").write_text("{}", encoding="utf-8")

    validated = Fire3DBackend._validate_official_result(tmp_path, scene_id)
    assert validated["reconstruction"]["status"] == "complete"

    artifacts = Fire3DBackend._discover_artifacts(tmp_path, scene_id)
    roles = [artifact.role for artifact in artifacts]
    assert "world-mesh" in roles
    assert "world-object" in roles
    assert "world-semantics" in roles
    assert "world-manifest" in roles
    assert FIRE3D_REVISION == "2368dd2f3909120cf90bbf8a17807abe9c41e600"


def test_fire3d_runtime_uses_prebuilt_flash_attn_artifact():
    runtime = (Path(__file__).parents[1] / "modal_fire3d/runtime.py").read_text(
        encoding="utf-8"
    )
    app = (Path(__file__).parents[1] / "modal_fire3d/app.py").read_text(encoding="utf-8")
    assert "pip install flash-attn==2.7.3 --no-build-isolation" not in runtime
    assert "fire3d-flash-attn-py310-cu128-torch271-sm90-v1" in runtime
    assert "fire3d-pytorch3d-py310-cu128-torch271-sm90-v1" in runtime
    assert "modal-build-artifacts" in runtime
    assert "_ensure_flash_attn(verify_cuda=True)" in app
    assert "_ensure_pytorch3d(verify_cuda=True)" in app
    assert '"--force-reinstall"' in app
    assert "sample_farthest_points(points, K=8)" in app
    assert "completed.stdout[-10000:]" in app
    assert "github.com/yyfz/Pi3.git" in runtime
    assert "PI3_SOURCE_REVISION" in runtime
    assert "raw_image_to_scene" in app
    assert "preload_raw_image_models" in app
