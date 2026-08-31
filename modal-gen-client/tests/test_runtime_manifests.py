from __future__ import annotations

import re

from modal_2d.deployment import deployment_manifest as deployment_2d
from modal_3d.deployment import deployment_manifest as deployment_3d
from modal_world.deployment import deployment_manifest as deployment_world

_TAG = re.compile(r"^[A-Za-z0-9._-]{1,50}$")


def test_runtime_revisions_are_valid_modal_deployment_tags():
    for manifest in (deployment_2d(), deployment_3d()):
        for target in manifest["targets"]:
            assert _TAG.fullmatch(target["revision"])


def test_every_runtime_declares_verifiable_weight_preparation():
    for manifest in (deployment_2d(), deployment_3d()):
        for target in manifest["targets"]:
            assert target["weights"]
            for spec in target["weights"]:
                assert spec["volume"]
                assert spec["requiredPaths"]
                assert spec["prepare"]


def test_3d_and_world_manifests_declare_huggingface_secrets():
    three_d = deployment_3d()
    by_app = {item["app"]: item for item in three_d["targets"]}
    assert "secrets" not in by_app["modal-3d-rembg"]
    for app in (
        "modal-3d-fastsam3d",
        "modal-3d-hunyuan",
        "modal-3d-hermit-trellis2-plus-plus",
        "modal-3d-pixal3d",
    ):
        assert by_app[app]["secrets"] == ["huggingface"]

    world = deployment_world()
    assert all(item["secrets"] == ["hyworld2-hf"] for item in world["targets"])
