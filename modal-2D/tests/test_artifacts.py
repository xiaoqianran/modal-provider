import hashlib
from pathlib import Path

import pytest

from modal_2d.artifacts import artifact_path, write_png


def test_write_png_is_atomic_and_described(tmp_path: Path):
    data = b"\x89PNG\r\n\x1a\nrest"
    descriptor = write_png(tmp_path, data)
    path = tmp_path / descriptor["remote_path"]

    assert path.read_bytes() == data
    assert descriptor["id"].startswith("art_")
    assert descriptor["role"] == "primary-image"
    assert descriptor["mime"] == "image/png"
    assert descriptor["bytes"] == len(data)
    assert descriptor["sha256"] == hashlib.sha256(data).hexdigest()
    assert artifact_path(tmp_path, descriptor["id"]) == path
    assert not list(tmp_path.rglob("*.part"))


def test_write_png_rejects_invalid_bytes(tmp_path: Path):
    with pytest.raises(ValueError, match="not a PNG"):
        write_png(tmp_path, b"not-png")
    assert not list(tmp_path.rglob("*.part"))
