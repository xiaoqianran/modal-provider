from __future__ import annotations

import unittest

import numpy as np

from modal_3d.sam3_1 import _mask_component_stats, _repair_mask_for_3d


class Sam3MaskRepairTests(unittest.TestCase):
    def test_coherent_mask_is_unchanged(self):
        mask = np.zeros((128, 128), dtype=bool)
        mask[20:100, 30:90] = True
        repaired, meta = _repair_mask_for_3d(mask)
        self.assertTrue(np.array_equal(repaired, mask))
        self.assertFalse(meta["applied"])
        self.assertEqual(meta["reason"], "already_coherent")

    def test_fragmented_object_is_reconnected_with_bounded_growth(self):
        mask = np.zeros((160, 160), dtype=bool)
        mask[20:80, 20:75] = True
        mask[84:140, 28:82] = True
        mask[45:125, 87:145] = True
        before = _mask_component_stats(mask)
        repaired, meta = _repair_mask_for_3d(mask)
        after = _mask_component_stats(repaired)
        self.assertGreater(before["major_count"], 1)
        self.assertTrue(meta["applied"])
        self.assertLess(after["major_count"], before["major_count"])
        self.assertLessEqual(meta["area_growth_fraction"], 0.12)

    def test_far_apart_objects_are_not_hallucinated_together(self):
        mask = np.zeros((256, 256), dtype=bool)
        mask[20:80, 20:80] = True
        mask[175:235, 175:235] = True
        repaired, meta = _repair_mask_for_3d(mask)
        self.assertTrue(np.array_equal(repaired, mask))
        self.assertFalse(meta["applied"])
        self.assertEqual(meta["reason"], "no_safe_repair")


if __name__ == "__main__":
    unittest.main()
