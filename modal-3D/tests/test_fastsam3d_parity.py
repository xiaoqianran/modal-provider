from __future__ import annotations

import unittest
from pathlib import Path

from modal_3d import fastsam3d_plus_plus as fastsam


class FastSAM3DParityTests(unittest.TestCase):
    def test_default_asset_policy_is_full_textured_path(self) -> None:
        policy = fastsam._asset_policy("textured")
        self.assertEqual(
            policy,
            {
                "with_mesh_postprocess": True,
                "with_texture_baking": True,
                "with_layout_postprocess": True,
                "use_vertex_color": False,
                "quality_profile": "base_color_textured",
            },
        )

    def test_fast_asset_policy_is_explicit_vertex_color_shortcut(self) -> None:
        policy = fastsam._asset_policy("vertex_color")
        self.assertFalse(policy["with_mesh_postprocess"])
        self.assertFalse(policy["with_texture_baking"])
        self.assertFalse(policy["with_layout_postprocess"])
        self.assertTrue(policy["use_vertex_color"])
        self.assertEqual(policy["quality_profile"], "vertex_color")

    def test_unknown_asset_mode_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "asset_mode must be one of"):
            fastsam._asset_policy("shortcut")

    def test_full_postprocess_runtime_dependencies_are_present(self) -> None:
        source = Path(fastsam.__file__).read_text(encoding="utf-8")
        for dependency in (
            "igraph==0.11.8",
            "open3d==0.18.0",
            "pymeshfix==0.17.0",
            "pyvista==0.44.2",
            "xatlas==0.0.9",
            "jaxtyping==0.2.36",
            "ninja==1.11.1.3",
            "rich==13.9.4",
            "fastsam3d-native-py311-cu121-torch251-sm89-v3",
            "2323de5905d5e90e035f792fe65bad0fedd413e7",
            "253ac4fcea7de5f396371124af597e6cc957bfae",
        ):
            self.assertIn(dependency, source)
        self.assertNotIn("uv pip install --system --no-build-isolation", source)
        self.assertIn("import torch, pytorch3d, gsplat, nvdiffrast.torch as dr", source)
        self.assertIn("python -m pip check", source)

    def test_full_pipeline_keeps_gaussian_decoder_configuration(self) -> None:
        source = Path(fastsam.__file__).read_text(encoding="utf-8")
        self.assertIn('"checkpoints/slat_decoder_gs_4.yaml"', source)
        self.assertIn('"checkpoints/slat_decoder_gs_4.ckpt"', source)
        self.assertNotIn("slat_decoder_gs_4_config_path: null", source)
        self.assertNotIn("slat_decoder_gs_4_ckpt_path: null", source)

    def test_patch_does_not_strip_official_postprocess_modules(self) -> None:
        patch = Path(fastsam.__file__).parent / "patches" / "fastsam3d.patch"
        text = patch.read_text(encoding="utf-8")
        for removed_import in (
            "-import xatlas",
            "-import pyvista as pv",
            "-from pymeshfix import _meshfix",
            "-import igraph",
            "-from .render_utils import render_multiview",
        ):
            self.assertNotIn(removed_import, text)
        self.assertIn('"backend": "gsplat"', text)


if __name__ == "__main__":
    unittest.main()
