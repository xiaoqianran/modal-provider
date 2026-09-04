from modal_world.artifact_bundles import ARTIFACT_VOLUME_NAME, all_artifact_bundles
from modal_world.deployment import deployment_manifest


def test_modal_world_declares_complete_build_artifact_prerequisites():
    manifest = deployment_manifest()
    bundles = all_artifact_bundles()
    expected_tags = {str(bundle["tag"]) for bundle in bundles}
    assert len(expected_tags) == 8
    assert len(manifest["targets"]) == 4
    for target in manifest["targets"]:
        assert target["required"] is True
        prerequisites = target["prerequisites"]
        assert len(prerequisites) == 8
        actual_tags = {
            spec["requiredPaths"][0].removesuffix(".wheels.zip") for spec in prerequisites
        }
        assert actual_tags == expected_tags
        assert {spec["volume"] for spec in prerequisites} == {ARTIFACT_VOLUME_NAME}
        for spec in prerequisites:
            assert len(spec["requiredPaths"]) == 3
            assert len(spec["prepare"]) == 1
            assert spec["prepare"][0]["module"].startswith("integrations.hyworld2.")


def test_public_bundle_recovery_uses_release_restore_and_private_bundles_use_builders():
    target = deployment_manifest()["targets"][0]
    by_tag = {
        spec["requiredPaths"][0].removesuffix(".wheels.zip"): spec for spec in target["prerequisites"]
    }
    public_restore = {
        "hyworld2-oss-native-py311-cu128-torch271-sm120-v1",
        "hyworld2-flash-attn-py311-cu128-torch271-sm120-v1",
        "hyworld2-flash-attn-py311-cu128-torch271-sm90-v1",
        "hyworld2-stage3-native-py311-cu128-torch271-sm90-v1",
    }
    for tag, spec in by_tag.items():
        call = spec["prepare"][0]
        if tag in public_restore:
            assert call["module"] == "integrations.hyworld2.restore"
            assert call["function"] == "restore_public_bundle"
            assert call["arguments"][0] == tag
        else:
            assert call["module"].startswith("integrations.hyworld2.build.hyworld2_")
            assert call["function"] == "build"
