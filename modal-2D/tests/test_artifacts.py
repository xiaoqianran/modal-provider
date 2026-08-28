import hashlib
from pathlib import Path

import pytest

from modal_2d.artifacts import artifact_path, inspect_png_header, write_png


def png_header(width: int = 1024, height: int = 1024) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )


def test_write_png_is_atomic_and_described(tmp_path: Path):
    data = png_header()
    descriptor = write_png(tmp_path, data)
    path = tmp_path / descriptor["remote_path"]

    assert path.read_bytes() == data
    assert descriptor["id"].startswith("art_")
    assert descriptor["role"] == "primary-image"
    sha256 = hashlib.sha256(data).hexdigest()
    assert descriptor["mediaType"] == "image/png"
    assert descriptor["digest"] == f"sha256:{sha256}"
    assert descriptor["producer"] == {
        "provider": "modal-2d",
        "operation": "modal-2d.image.text_to_image.v1",
    }
    assert descriptor["mime"] == "image/png"
    assert descriptor["bytes"] == len(data)
    assert descriptor["sha256"] == sha256
    assert artifact_path(tmp_path, descriptor["id"]) == path
    assert not list(tmp_path.rglob("*.part"))


def test_write_png_rejects_invalid_bytes(tmp_path: Path):
    with pytest.raises(ValueError, match="not a PNG"):
        write_png(tmp_path, b"not-png")
    with pytest.raises(ValueError, match="must be 1024x1024"):
        write_png(tmp_path, png_header(width=512))
    assert not list(tmp_path.rglob("*.part"))


def test_inspect_png_header_reads_verified_dimensions():
    assert inspect_png_header(png_header()) == (1024, 1024)
