from __future__ import annotations

import binascii
import tempfile
import unittest
import zlib
from pathlib import Path

from modal_3d.common import validate_canonical_png
from modal_3d.png import foreground_stats


def chunk(kind: bytes, body: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(body, crc) & 0xFFFFFFFF
    return len(body).to_bytes(4, "big") + kind + body + crc.to_bytes(4, "big")


def rgba_png(
    width: int = 1024,
    height: int = 1024,
    *,
    foreground_alpha: int = 255,
    background_alpha: int = 0,
    foreground_rgb: tuple[int, int, int] = (120, 140, 160),
) -> bytes:
    ihdr = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes([8, 6, 0, 0, 0])
    )
    foreground = bytes([*foreground_rgb, foreground_alpha])
    background = bytes([0, 0, 0, background_alpha])
    rows = []
    split = width // 2
    for _ in range(height):
        rows.append(b"\x00" + background * split + foreground * (width - split))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), level=1))
        + chunk(b"IEND", b"")
    )


class CanonicalContractTests(unittest.TestCase):
    def _write(self, data: bytes) -> Path:
        temp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        temp.write(data)
        temp.close()
        self.addCleanup(Path(temp.name).unlink, missing_ok=True)
        return Path(temp.name)

    def test_accepts_visible_foreground_with_transparent_background(self) -> None:
        result = validate_canonical_png(self._write(rgba_png()))
        self.assertEqual(result["width"], 1024)
        self.assertEqual(result["height"], 1024)
        self.assertEqual(result["mode"], "RGBA")
        self.assertEqual(result["alpha_min"], 0)
        self.assertEqual(result["alpha_max"], 255)

    def test_foreground_stats_detect_benchmark_rgb_loss(self) -> None:
        colored = rgba_png()
        black = rgba_png(foreground_rgb=(0, 0, 0))
        colored_stats = foreground_stats(colored, 1024, 1024)
        black_stats = foreground_stats(black, 1024, 1024)
        self.assertGreater(colored_stats["foreground_rgb_nonzero_fraction"], 0.99)
        self.assertEqual(black_stats["foreground_rgb_nonzero_fraction"], 0.0)
        self.assertEqual(colored_stats["foreground_bbox"], [512, 0, 1024, 1024])

    def test_rejects_wrong_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "1024x1024"):
            validate_canonical_png(self._write(rgba_png(1024, 768)))

    def test_rejects_opaque_background(self) -> None:
        with self.assertRaisesRegex(ValueError, "transparent background"):
            validate_canonical_png(
                self._write(rgba_png(background_alpha=255, foreground_alpha=255))
            )

    def test_rejects_empty_foreground(self) -> None:
        with self.assertRaisesRegex(ValueError, "no visible foreground"):
            validate_canonical_png(
                self._write(rgba_png(background_alpha=0, foreground_alpha=0))
            )

    def test_rejects_invalid_crc(self) -> None:
        data = bytearray(rgba_png())
        data[-1] ^= 0xFF
        with self.assertRaisesRegex(ValueError, "CRC"):
            validate_canonical_png(self._write(bytes(data)))

    def test_rejects_non_png(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid PNG"):
            validate_canonical_png(self._write(b"not a png"))


if __name__ == "__main__":
    unittest.main()

class CanonicalInputIdentityTests(unittest.TestCase):
    def test_content_addressed_filename_must_match_bytes(self) -> None:
        import hashlib
        from modal_3d.common import validate_canonical_input

        payload = rgba_png()
        with tempfile.TemporaryDirectory() as temp_dir:
            good = Path(temp_dir) / f"{hashlib.sha256(payload).hexdigest()}.png"
            good.write_bytes(payload)
            self.assertEqual(validate_canonical_input(good)["sha256"], good.stem)

            bad = Path(temp_dir) / ("0" * 64 + ".png")
            bad.write_bytes(payload)
            with self.assertRaisesRegex(ValueError, "SHA256"):
                validate_canonical_input(bad)

    def test_non_content_addressed_filename_keeps_legacy_compatibility(self) -> None:
        from modal_3d.common import validate_canonical_input

        payload = rgba_png()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.png"
            path.write_bytes(payload)
            self.assertEqual(validate_canonical_input(path)["width"], 1024)
