import pytest

from modal_world.semantic_compile import compile_hyworld_semantics


def test_category_only_semantics_stays_v1_and_does_not_invent_instances():
    payload = compile_hyworld_semantics(["tree", "Bench", "bench", ""])
    assert payload == {
        "schemaVersion": 1,
        "granularity": "category",
        "categories": ["tree", "Bench"],
        "instances": [],
        "provenance": {
            "kind": "hyworld2-object-labels",
            "categoriesSource": "../objects.json",
        },
    }


def test_target_camera_evidence_becomes_point_scale_instances_without_fake_bbox():
    payload = compile_hyworld_semantics(
        ["bench", "door"],
        [{
            "id": 4, "label": "door", "score": 0.95,
            "center_point_3d": [1, 2, 3], "scale_3d": 0.47,
            "left_point_3d": [0.8, 2.0, 3.0], "right_point_3d": [1.2, 2.0, 3.0],
            "mask_area": 0.01, "depth_distance": 1.7, "direction": "Left",
            "bearing_angle": -62.25, "total_rank": 2,
        }],
    )
    assert payload["schemaVersion"] == 2
    assert payload["granularity"] == "instance"
    instance = payload["instances"][0]
    assert instance["id"] == "hyworld2-target-4"
    assert instance["label"] == "door"
    assert instance["confidence"] == 0.95
    assert instance["localization"] == {
        "kind": "point-scale", "center": [1.0, 2.0, 3.0], "scale": 0.47,
        "leftPoint": [0.8, 2.0, 3.0], "rightPoint": [1.2, 2.0, 3.0],
    }
    assert "bbox" not in instance
    assert instance["evidence"]["sourceId"] == 4
    assert payload["provenance"]["kind"] == "hyworld2-sam3-depth-targets"


def test_invalid_target_evidence_is_rejected_instead_of_fabricated():
    payload = compile_hyworld_semantics(["door"], [
        {"id": 1, "label": "door", "score": 0.9, "center_point_3d": [1, 2], "scale_3d": 1},
        {"id": 2, "label": "door", "score": 2.0, "center_point_3d": [1, 2, 3], "scale_3d": 1},
        {"id": 3, "label": "door", "score": 0.9, "center_point_3d": [1, 2, 3], "scale_3d": 0},
    ])
    assert payload["schemaVersion"] == 1
    assert payload["instances"] == []


def test_semantic_sources_must_be_lists():
    with pytest.raises(TypeError):
        compile_hyworld_semantics({"door": 1})
    with pytest.raises(TypeError):
        compile_hyworld_semantics(["door"], {"id": 1})
