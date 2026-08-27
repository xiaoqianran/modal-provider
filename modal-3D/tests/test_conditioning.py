from __future__ import annotations

import io
import unittest

from PIL import Image

from modal_3d.conditioning import BackgroundMaskRequired, condition_image


def image_bytes(mode: str, size=(48, 32), *, alpha: int | None = None) -> bytes:
    if mode == "RGBA":
        image = Image.new("RGBA", size, (220, 20, 20, 0 if alpha is None else alpha))
        if alpha is not None and alpha < 255:
            # Transparent border with an opaque foreground verifies alpha preservation/bbox.
            foreground = Image.new("RGBA", (20, 20), (220, 20, 20, 255))
            image.alpha_composite(foreground, (14, 6))
    else:
        image = Image.new(mode, size, (220, 20, 20))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def mask_bytes(size=(48, 32)) -> bytes:
    mask = Image.new("L", size, 0)
    mask.paste(255, (14, 6, 34, 26))
    output = io.BytesIO()
    mask.save(output, format="PNG")
    return output.getvalue()


class ConditioningTests(unittest.TestCase):
    def assert_canonical(self, payload: dict[str, object]) -> None:
        data = payload["canonical_bytes"]
        self.assertIsInstance(data, bytes)
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.size, (1024, 1024))
            self.assertNotEqual(image.getchannel("A").getextrema(), (255, 255))

    def test_existing_meaningful_alpha_is_preserved(self) -> None:
        payload = condition_image(image_bytes("RGBA", alpha=0))
        self.assertEqual(payload["strategy"], "preserve-alpha")
        self.assertEqual(payload["source_format"], "png")
        self.assertGreater(payload["foreground_ratio"], 0)
        self.assert_canonical(payload)

    def test_opaque_image_requires_background_mask(self) -> None:
        with self.assertRaises(BackgroundMaskRequired):
            condition_image(image_bytes("RGB"))

    def test_predicted_mask_conditions_opaque_image(self) -> None:
        payload = condition_image(image_bytes("RGB"), mask_bytes())
        self.assertEqual(payload["strategy"], "birefnet")
        self.assertEqual(payload["foreground_bbox"], [14, 6, 34, 26])
        self.assert_canonical(payload)

    def test_rejects_unsupported_image_format(self) -> None:
        image = Image.new("RGB", (32, 32), "red")
        output = io.BytesIO()
        image.save(output, format="BMP")
        with self.assertRaisesRegex(ValueError, "unsupported source image format"):
            condition_image(output.getvalue())


if __name__ == "__main__":
    unittest.main()
