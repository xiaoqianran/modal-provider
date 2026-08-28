from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath

from modal_3d import fastsam3d_plus_plus
from modal_3d.common import ARTIFACT_ROOT


class WindowsDeployContractTests(unittest.TestCase):
    def test_linux_image_paths_are_platform_neutral_on_windows(self) -> None:
        self.assertIsInstance(fastsam3d_plus_plus.SRC, PurePosixPath)
        self.assertIsInstance(fastsam3d_plus_plus.MODEL_DIR, PurePosixPath)
        self.assertEqual(str(fastsam3d_plus_plus.SRC), "/opt/fastsam3d-plus-plus")
        self.assertEqual(str(fastsam3d_plus_plus.MODEL_DIR), "/models/sam3d")
        self.assertEqual(str(fastsam3d_plus_plus.PIPELINE), "/models/sam3d/checkpoints/pipeline.fast.yaml")
        source = Path(fastsam3d_plus_plus.__file__).read_text(encoding="utf-8")
        self.assertIn("OmegaConf.load(str(PIPELINE))", source)
        # ARTIFACT_ROOT must stay a plain string: a Windows Path captured here
        # cannot be unpickled inside Modal's Linux containers.
        self.assertIsInstance(ARTIFACT_ROOT, str)
        self.assertEqual(ARTIFACT_ROOT, "/artifacts")

    def test_fastsam_patch_is_lf_normalized(self) -> None:
        patch = Path(fastsam3d_plus_plus.__file__).parent / "patches" / "fastsam3d.patch"
        data = patch.read_bytes()
        self.assertNotIn(b"\r", data)
        self.assertIn(b"mmap=True", data)


if __name__ == "__main__":
    unittest.main()
