import json
from pathlib import Path

import pytest

from modal_world.worldgen_policy import (
    GARDEN_ALLOWED_SEMANTICS,
    camera_frame_count,
    sanitize_semantic_labels,
    select_camera_files,
)


def _camera(tmp_path: Path, group: str, traj: int, frames: int) -> Path:
    path = tmp_path / "render_results" / f"{group}_0" / f"traj{traj}" / "camera.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"extrinsic": [[0]] * frames}))
    return path


def test_camera_budget_round_robins_trajectory_groups(tmp_path: Path):
    cameras = [
        _camera(tmp_path, "view", 0, 80),
        _camera(tmp_path, "view", 1, 80),
        _camera(tmp_path, "target", 0, 80),
        _camera(tmp_path, "wonder", 0, 80),
        _camera(tmp_path, "reconstruct", 0, 80),
    ]
    selected = select_camera_files(cameras, 320)
    assert len(selected) == 4
    assert sum(camera_frame_count(path) for path in selected) == 320
    assert {path.parent.parent.name.split("_")[0] for path in selected} == {
        "view",
        "target",
        "wonder",
        "reconstruct",
    }


def test_camera_budget_none_preserves_all(tmp_path: Path):
    cameras = [_camera(tmp_path, "view", 0, 10), _camera(tmp_path, "target", 0, 20)]
    assert select_camera_files(cameras, None) == sorted(cameras)


def test_camera_budget_rejects_non_positive(tmp_path: Path):
    with pytest.raises(ValueError):
        select_camera_files([_camera(tmp_path, "view", 0, 10)], 0)


def test_garden_semantics_remove_unrequested_categories():
    labels = ["tree", "bench", "statue", "trash can", "Butterfly", "gazebo"]
    kept, removed = sanitize_semantic_labels(labels)
    assert kept == ["tree", "bench", "gazebo"]
    assert removed == ["statue", "trash can", "Butterfly"]
    assert {label.lower() for label in kept} <= GARDEN_ALLOWED_SEMANTICS


def test_garden_semantics_require_list():
    with pytest.raises(TypeError):
        sanitize_semantic_labels({"tree": 1})


def test_garden_prompt_forbids_transient_visual_hallucinations():
    source = Path("modal_world/app.py").read_text()
    start = source.index("GARDEN_PANO_PROMPT = (")
    end = source.index("\n)\n", start)
    prompt = source[start:end].lower()
    for phrase in (
        "no animals",
        "no birds",
        "no butterflies",
        "no insects",
        "no statues",
        "no trash cans",
        "no transient or moving objects",
    ):
        assert phrase in prompt


def test_non_reference_worlds_use_camera_budget_but_case000_does_not():
    source = Path("modal_world/stage2_app.py").read_text()
    assert (
        'frame_budget = None if job_id == "case000" else NON_REFERENCE_CAMERA_FRAME_BUDGET'
        in source
    )
    assert '"camera_frame_budget": frame_budget' in source
    assert "stale_output.unlink()" in source
