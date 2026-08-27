from __future__ import annotations

import io

import pytest
from PIL import Image


@pytest.fixture
def source_png() -> bytes:
    image = Image.new("RGB", (640, 480), (255, 255, 255))
    image.paste((220, 20, 20), (220, 120, 420, 360))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def source_jpeg() -> bytes:
    image = Image.new("RGB", (320, 240), (220, 20, 20))
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=92)
    return stream.getvalue()


@pytest.fixture
def source_webp() -> bytes:
    image = Image.new("RGBA", (256, 192), (220, 20, 20, 180))
    stream = io.BytesIO()
    image.save(stream, format="WEBP", lossless=True)
    return stream.getvalue()


@pytest.fixture
def glb_bytes() -> bytes:
    body = b"\x00" * 16
    total = 12 + len(body)
    return b"glTF" + (2).to_bytes(4, "little") + total.to_bytes(4, "little") + body
