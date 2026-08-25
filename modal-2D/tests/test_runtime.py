from pathlib import Path

from modal_2d.runtime import model_snapshot_ready, validate_image_size


def test_snapshot_ready_requires_marker_and_model_index(tmp_path: Path):
    path = tmp_path / "model"
    path.mkdir()
    assert model_snapshot_ready(path) is False
    (path / "model_index.json").write_text("{}")
    assert model_snapshot_ready(path) is False
    (path / ".complete").write_text("repo")
    assert model_snapshot_ready(path) is True


def test_generated_image_size_must_match_request():
    class Image:
        size = (1024, 1024)

    validate_image_size(Image(), {"width": 1024, "height": 1024})
    Image.size = (512, 1024)
    import pytest

    with pytest.raises(RuntimeError, match="unexpected image size"):
        validate_image_size(Image(), {"width": 1024, "height": 1024})
