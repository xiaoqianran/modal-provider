from __future__ import annotations

import io
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from modal_3d import pixal3d


class PixalSafeOptimizationTests(unittest.TestCase):
    def test_moge_in_memory_pixels_equal_lossless_png_roundtrip(self) -> None:
        rng = np.random.default_rng(20260908)
        rgba = rng.integers(0, 256, size=(96, 128, 4), dtype=np.uint8)
        source = Image.fromarray(rgba, mode="RGBA")

        direct = pixal3d._moge_rgb_float32(source)
        encoded = io.BytesIO()
        source.save(encoded, format="PNG")
        encoded.seek(0)
        with Image.open(encoded) as reopened:
            legacy = np.array(reopened.convert("RGB")).astype(np.float32) / 255.0

        np.testing.assert_array_equal(direct, legacy)

    def test_shared_backbones_keep_branch_specific_conditioners(self) -> None:
        source = Path(pixal3d.__file__).read_text(encoding="utf-8")
        self.assertIn("return_value=shared_dino", source)
        self.assertIn("model.naf_model = shared_naf", source)
        self.assertIn("DINO sharing invariant failed", source)
        self.assertIn("NAF sharing invariant failed", source)
        for branch in ("ss", "shape_512", "shape_1024", "tex_1024"):
            self.assertIn(f'image_cond_configs["{branch}"]', source)

    def test_hermit_and_pixal_pin_uv_build_tool(self) -> None:
        for module in (pixal3d,):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertIn("python -m pip install uv==0.12.5", source)
            self.assertNotIn("pip install --upgrade uv", source)

        from modal_3d import hermit_trellis2_plus_plus

        source = Path(hermit_trellis2_plus_plus.__file__).read_text(encoding="utf-8")
        self.assertIn("python -m pip install uv==0.12.5", source)
        self.assertNotIn("pip install --upgrade uv", source)

    def test_pixal_release_wheel_download_retries_transient_failures(self) -> None:
        source = Path(pixal3d.__file__).read_text(encoding="utf-8")
        self.assertIn("--retry 5 --retry-all-errors --retry-delay 2", source)

    def test_hunyuan_profile_patch_is_instrumentation_only(self) -> None:
        patch_path = (
            Path(pixal3d.__file__).parent / "patches" / "hunyuan_paint_profile.patch"
        )
        text = patch_path.read_text(encoding="utf-8")
        self.assertIn('mark("multiview_diffusion_s"', text)
        self.assertIn('timings["super_resolution_albedo_s"]', text)
        self.assertIn('timings["super_resolution_mr_s"]', text)
        self.assertIn("self.last_timings = timings", text)
        # Every removed line in the patch is context/file metadata; instrumentation
        # must not replace a model call or a quality parameter.
        removed_code = [
            line
            for line in text.splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]
        self.assertEqual(removed_code, [])


if __name__ == "__main__":
    unittest.main()
