from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modal_3d.pixal3d_patch import (
    EXPECTED_STAGE_CACHE_CALLS,
    PIPELINE_STAGE_NAMES,
    STAGE_CACHE_ENV,
    STAGE_PROFILE_MARKER,
    patch_pixal3d_stage_cache_guard,
    patch_pixal3d_stage_profiling,
)


class Pixal3DStagePatchTests(unittest.TestCase):
    def _cache_source_tree(
        self, calls: int = EXPECTED_STAGE_CACHE_CALLS
    ) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        target = Path(temp.name) / "pixal3d/pipelines/pixal3d_image_to_3d.py"
        target.parent.mkdir(parents=True)
        body = "from typing import *\nimport torch\n\nclass Pipeline:\n    def run(self):\n"
        body += "\n".join("        torch.cuda.empty_cache()" for _ in range(calls))
        body += "\n"
        target.write_text(body, encoding="utf-8")
        return temp, target

    def _profile_source_tree(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        target = Path(temp.name) / "pixal3d/pipelines/pixal3d_image_to_3d.py"
        target.parent.mkdir(parents=True)
        target.write_text(
            """from typing import *
import torch

class Pipeline:
    def run(self, seed=42):
        torch.manual_seed(seed)

        # ---- Stage 1: Sparse Structure (proj) ----
        coords = torch.zeros((2, 4))
        torch.cuda.empty_cache()

        # ---- Stage 2: Shape LR 512 (proj) ----
        lr_slat = type('S', (), {'coords': coords})()
        torch.cuda.empty_cache()

        # ---- Stage 3a: Upsample LR → HR ----
        actual_hr_resolution = 1536
        hr_coords_unique = coords
        torch.cuda.empty_cache()

        # ---- Stage 3b: Shape HR (proj) ----
        shape_slat = type('S', (), {'coords': coords})()
        torch.cuda.empty_cache()

        # ---- Stage 4: Texture (proj) ----
        tex_slat = type('S', (), {'coords': coords})()
        torch.cuda.empty_cache()

        # ---- Stage 5: Decode ----
        res = actual_hr_resolution
        out_mesh = self.decode_latent(shape_slat, tex_slat, res)
        if True:
            return out_mesh, (shape_slat, tex_slat, res)
""",
            encoding="utf-8",
        )
        return temp, target

    def test_cache_patch_exactly_five_calls_and_preserves_default_behavior(self) -> None:
        temp, target = self._cache_source_tree()
        self.addCleanup(temp.cleanup)

        result = patch_pixal3d_stage_cache_guard(temp.name)
        source = target.read_text(encoding="utf-8")

        self.assertTrue(result["patched"])
        self.assertEqual(result["guarded_calls"], EXPECTED_STAGE_CACHE_CALLS)
        self.assertEqual(result["env"], STAGE_CACHE_ENV)
        self.assertEqual(source.count(f'os.environ.get("{STAGE_CACHE_ENV}", "0")'), 5)
        self.assertEqual(source.count("torch.cuda.empty_cache()"), 5)
        self.assertIn('!= "1"', source)
        self.assertIn("import os\n", source)

    def test_cache_patch_is_idempotent(self) -> None:
        temp, target = self._cache_source_tree()
        self.addCleanup(temp.cleanup)

        first = patch_pixal3d_stage_cache_guard(temp.name)
        first_source = target.read_text(encoding="utf-8")
        second = patch_pixal3d_stage_cache_guard(temp.name)

        self.assertTrue(first["patched"])
        self.assertFalse(second["patched"])
        self.assertEqual(target.read_text(encoding="utf-8"), first_source)

    def test_cache_source_drift_fails_closed(self) -> None:
        temp, _ = self._cache_source_tree(calls=4)
        self.addCleanup(temp.cleanup)

        with self.assertRaisesRegex(RuntimeError, "source drift"):
            patch_pixal3d_stage_cache_guard(temp.name)

    def test_cache_partial_patch_fails_closed(self) -> None:
        temp, target = self._cache_source_tree()
        self.addCleanup(temp.cleanup)
        source = target.read_text(encoding="utf-8")
        source = source.replace(
            "        torch.cuda.empty_cache()",
            f'        if os.environ.get("{STAGE_CACHE_ENV}", "0") != "1":\n'
            "            torch.cuda.empty_cache()",
            1,
        )
        target.write_text(source, encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "partial"):
            patch_pixal3d_stage_cache_guard(temp.name)

    def test_profile_patch_instruments_all_native_stages(self) -> None:
        temp, target = self._profile_source_tree()
        self.addCleanup(temp.cleanup)

        result = patch_pixal3d_stage_profiling(temp.name)
        source = target.read_text(encoding="utf-8")

        self.assertTrue(result["patched"])
        self.assertEqual(tuple(result["stages"]), PIPELINE_STAGE_NAMES)
        self.assertIn(STAGE_PROFILE_MARKER, source)
        self.assertIn("import time\n", source)
        for name in PIPELINE_STAGE_NAMES:
            self.assertIn(f'self.last_stage_timings["{name}_s"]', source)
        self.assertIn('self.last_stage_metrics["actual_hr_resolution"]', source)
        self.assertIn('self.last_stage_metrics["texture_tokens"]', source)

    def test_profile_then_cache_patch_compose_and_are_idempotent(self) -> None:
        temp, target = self._profile_source_tree()
        self.addCleanup(temp.cleanup)

        patch_pixal3d_stage_profiling(temp.name)
        patch_pixal3d_stage_cache_guard(temp.name)
        first_source = target.read_text(encoding="utf-8")
        second_profile = patch_pixal3d_stage_profiling(temp.name)
        second_cache = patch_pixal3d_stage_cache_guard(temp.name)

        self.assertFalse(second_profile["patched"])
        self.assertFalse(second_cache["patched"])
        self.assertEqual(target.read_text(encoding="utf-8"), first_source)

    def test_profile_source_drift_fails_closed(self) -> None:
        temp, target = self._profile_source_tree()
        self.addCleanup(temp.cleanup)
        source = target.read_text(encoding="utf-8").replace(
            "        # ---- Stage 4: Texture (proj) ----\n", "        # renamed upstream\n"
        )
        target.write_text(source, encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "stage anchor"):
            patch_pixal3d_stage_profiling(temp.name)


if __name__ == "__main__":
    unittest.main()
