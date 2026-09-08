from __future__ import annotations

import unittest

import numpy as np

from modal_3d.o_voxel_contract import REQUIRED_PBR_CHANNELS, validate_o_voxel_pbr_intermediate


class OVoxelIntermediateContractTests(unittest.TestCase):
    def _valid(self, **overrides):
        values = {
            "vertices": np.zeros((8, 3), dtype=np.float32),
            "faces": np.zeros((12, 3), dtype=np.int32),
            "attrs": np.zeros((32, 6), dtype=np.float32),
            "coords": np.zeros((32, 3), dtype=np.int32),
            "attr_layout": {
                "base_color": slice(0, 3),
                "metallic": slice(3, 4),
                "roughness": slice(4, 5),
                "alpha": slice(5, 6),
            },
            "grid_size": 1536,
        }
        values.update(overrides)
        return validate_o_voxel_pbr_intermediate(**values)

    def test_accepts_full_pbr_intermediate_without_mutating_it(self) -> None:
        attrs = np.arange(32 * 6, dtype=np.float32).reshape(32, 6)
        before = attrs.copy()
        result = self._valid(attrs=attrs)
        np.testing.assert_array_equal(attrs, before)
        self.assertEqual(result["pbr_channels"], list(REQUIRED_PBR_CHANNELS))
        self.assertEqual(result["grid_size"], 1536)
        self.assertEqual(result["coords"], 32)

    def test_accepts_trellis_voxel_size_contract(self) -> None:
        result = self._valid(grid_size=None, voxel_size=1.0 / 1536.0)
        self.assertAlmostEqual(result["voxel_size"], 1.0 / 1536.0)

    def test_rejects_missing_pbr_channel(self) -> None:
        layout = {
            "base_color": slice(0, 3),
            "metallic": slice(3, 4),
            "roughness": slice(4, 5),
        }
        with self.assertRaisesRegex(ValueError, "alpha"):
            self._valid(attr_layout=layout)

    def test_rejects_invalid_layout_slice(self) -> None:
        layout = {
            "base_color": slice(0, 3),
            "metallic": 3,
            "roughness": slice(4, 5),
            "alpha": slice(5, 6),
        }
        with self.assertRaisesRegex(TypeError, "metallic"):
            self._valid(attr_layout=layout)

    def test_rejects_empty_semantic_attributes(self) -> None:
        with self.assertRaisesRegex(ValueError, "attrs is empty"):
            self._valid(attrs=np.empty((0, 6), dtype=np.float32))

    def test_rejects_attrs_coords_count_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "attrs/coords count mismatch"):
            self._valid(coords=np.zeros((31, 3), dtype=np.int32))

    def test_rejects_attr_tensor_narrower_than_declared_pbr_layout(self) -> None:
        with self.assertRaisesRegex(ValueError, "attrs width"):
            self._valid(attrs=np.zeros((32, 5), dtype=np.float32))

    def test_rejects_missing_spatial_scale(self) -> None:
        with self.assertRaisesRegex(ValueError, "grid_size or voxel_size"):
            self._valid(grid_size=None, voxel_size=None)


if __name__ == "__main__":
    unittest.main()
