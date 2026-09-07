from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modal_3d.pixal3d_patch import (
    EXPECTED_STAGE_CACHE_CALLS,
    STAGE_CACHE_ENV,
    patch_pixal3d_stage_cache_guard,
)


class Pixal3DStageCachePatchTests(unittest.TestCase):
    def _source_tree(self, calls: int = EXPECTED_STAGE_CACHE_CALLS) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        target = Path(temp.name) / "pixal3d/pipelines/pixal3d_image_to_3d.py"
        target.parent.mkdir(parents=True)
        body = "from typing import *\nimport torch\n\nclass Pipeline:\n    def run(self):\n"
        body += "\n".join("        torch.cuda.empty_cache()" for _ in range(calls))
        body += "\n"
        target.write_text(body, encoding="utf-8")
        return temp, target

    def test_patches_exactly_five_calls_and_preserves_default_behavior(self) -> None:
        temp, target = self._source_tree()
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

    def test_patch_is_idempotent(self) -> None:
        temp, target = self._source_tree()
        self.addCleanup(temp.cleanup)

        first = patch_pixal3d_stage_cache_guard(temp.name)
        first_source = target.read_text(encoding="utf-8")
        second = patch_pixal3d_stage_cache_guard(temp.name)

        self.assertTrue(first["patched"])
        self.assertFalse(second["patched"])
        self.assertEqual(target.read_text(encoding="utf-8"), first_source)

    def test_source_drift_fails_closed(self) -> None:
        temp, _ = self._source_tree(calls=4)
        self.addCleanup(temp.cleanup)

        with self.assertRaisesRegex(RuntimeError, "source drift"):
            patch_pixal3d_stage_cache_guard(temp.name)

    def test_partial_patch_fails_closed(self) -> None:
        temp, target = self._source_tree()
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


if __name__ == "__main__":
    unittest.main()
