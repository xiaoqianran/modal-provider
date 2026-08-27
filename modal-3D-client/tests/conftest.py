from __future__ import annotations

import io

import pytest
from PIL import Image


@pytest.fixture
def canonical_png() -> bytes:
    image = Image.new("RGBA", (1024, 1024), (255, 0, 0, 255))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def glb_bytes() -> bytes:
    body = b"\x00" * 16
    total = 12 + len(body)
    return b"glTF" + (2).to_bytes(4, "little") + total.to_bytes(4, "little") + body
