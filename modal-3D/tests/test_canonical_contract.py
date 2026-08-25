from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modal_3d.common import PNG_SIGNATURE, validate_canonical_png


def png_header(width: int, height: int, bit_depth: int = 8, color_type: int = 6) -> bytes:
    return (
        PNG_SIGNATURE
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes([bit_depth, color_type, 0, 0, 0])
        + b"\x00\x00\x00\x00"
    )


class CanonicalContractTests(unittest.TestCase):
    def _write(self, data: bytes) -> Path:
        temp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        temp.write(data)
        temp.close()
        self.addCleanup(Path(temp.name).unlink, missing_ok=True)
        return Path(temp.name)

    def test_accepts_1024_rgba_png_header(self) -> None:
        validate_canonical_png(self._write(png_header(1024, 1024)))

    def test_rejects_wrong_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "1024x1024"):
            validate_canonical_png(self._write(png_header(1024, 768)))

    def test_rejects_rgb_without_alpha_channel(self) -> None:
        with self.assertRaisesRegex(ValueError, "8-bit RGBA"):
            validate_canonical_png(self._write(png_header(1024, 1024, color_type=2)))

    def test_rejects_non_png(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid PNG"):
            validate_canonical_png(self._write(b"not a png"))


if __name__ == "__main__":
    unittest.main()
