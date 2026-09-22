from __future__ import annotations

from pathlib import Path

import pytest

from modal_3d import operation_runner
from modal_3d.deployment import deployment_manifest
from modal_3d.operations import (
    options_for,
    required_roles_for,
    revision_for,
    worker_for,
)


def test_rig_and_pose_contracts_are_dedicated_workers():
    assert worker_for("rig") == "modal-3d-tokenrig"
    assert worker_for("pose") == "modal-3d-pose"
    assert revision_for("rig").startswith("skintokens-273b691d")
    assert revision_for("pose") == "blender-pose-v1"
    assert required_roles_for("rig") == [
        "primary-glb",
        "rig-report",
        "quality-report",
    ]
    assert required_roles_for("pose") == [
        "primary-glb",
        "pose-report",
        "quality-report",
    ]


def test_rig_defaults_match_official_cli_defaults():
    assert options_for("rig") == {
        "top_k": 5,
        "top_p": 0.95,
        "temperature": 1.0,
        "repetition_penalty": 2.0,
        "num_beams": 10,
        "preserve_texture_and_scale": True,
        "postprocess_skin": False,
    }


def test_pose_profiles_are_explicit_and_bounded():
    assert options_for("pose") == {
        "preset": "t_pose",
        "skeleton_profile": "auto",
    }
    for preset in ("t_pose", "a_pose", "rest"):
        assert options_for("pose", {"preset": preset})["preset"] == preset
    assert options_for("pose", {"skeleton_profile": "tokenrig"})["skeleton_profile"] == "tokenrig"
    with pytest.raises(ValueError):
        options_for("pose", {"preset": "dance"})


def test_deployment_manifest_has_tokenrig_and_weightless_pose():
    targets = {row["app"]: row for row in deployment_manifest()["targets"]}
    tokenrig = targets["modal-3d-tokenrig"]
    assert tokenrig["models"] == ["rig"]
    assert tokenrig["weights"][0]["requiredPaths"] == [
        "tokenrig/experiments/skin_vae_2_10_32768/last.ckpt",
        "tokenrig/experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt",
        "tokenrig/models/Qwen3-0.6B/config.json",
    ]
    pose = targets["modal-3d-pose"]
    assert pose["models"] == ["pose"]
    assert pose["weightless"] is True
    assert pose["weights"] == []


def test_tokenrig_worker_pins_official_source_and_checkpoint_revision():
    source = (
        Path(__file__).resolve().parents[1] / "modal_3d" / "tokenrig_worker.py"
    ).read_text(encoding="utf-8")
    assert (
        'SOURCE_REVISION = "273b691d35989d71cd17ff2895fdc735097b92d1"'
        in source
    )
    assert 'WEIGHT_REVISION = "79736ca"' in source
    assert 'QWEN_REVISION = "c1899de"' in source
    assert 'GPU = "A100-80GB"' in source
    assert '"libxrender1"' in source
    assert "import bpy; print('bpy', bpy.app.version_string)" in source


def test_pose_worker_supports_tokenrig_and_validates_bpy_runtime():
    source = (
        Path(__file__).resolve().parents[1] / "modal_3d" / "pose_worker.py"
    ).read_text(encoding="utf-8")
    assert 'return "tokenrig", mapping' in source
    assert '"libxrender1"' in source
    assert "import bpy; print('bpy', bpy.app.version_string)" in source


def test_glb_validation_modes_are_not_globally_relaxed(tmp_path, monkeypatch):
    path = tmp_path / "fixture.glb"
    path.write_bytes(b"glTF" + b"\0" * 64)
    monkeypatch.setattr(operation_runner, "validate_glb", lambda _path: None)

    static_doc = {
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [{"mesh": 0}],
    }
    monkeypatch.setattr(operation_runner, "_glb_json_document", lambda _path: static_doc)
    operation_runner.validate_file(path, "model/gltf-binary", glb_mode="static")
    with pytest.raises(ValueError, match="at least one skin"):
        operation_runner.validate_file(path, "model/gltf-binary", glb_mode="rigged")

    rigged_doc = {
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "JOINTS_0": 1,
                            "WEIGHTS_0": 2,
                        }
                    }
                ]
            }
        ],
        "nodes": [{"mesh": 0}, {"name": "bone"}],
        "skins": [{"joints": [1]}],
    }
    monkeypatch.setattr(operation_runner, "_glb_json_document", lambda _path: rigged_doc)
    operation_runner.validate_file(path, "model/gltf-binary", glb_mode="rigged")
    with pytest.raises(ValueError, match="static GLB"):
        operation_runner.validate_file(path, "model/gltf-binary", glb_mode="static")

    animated = {**rigged_doc, "animations": [{"channels": [], "samplers": []}]}
    monkeypatch.setattr(operation_runner, "_glb_json_document", lambda _path: animated)
    with pytest.raises(ValueError, match="pose snapshot"):
        operation_runner.validate_file(path, "model/gltf-binary", glb_mode="posed")
