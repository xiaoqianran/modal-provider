import importlib.util
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parents[1]
RUNTIME = ROOT / "runtime" / "embodiedgen_affordance_l40s.py"
spec = importlib.util.spec_from_file_location("embodiedgen_affordance_glb", RUNTIME)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class GlbAccessorBoundsTest(unittest.TestCase):
    def _doc(self, *, buffer_view=0, view_offset=0, view_length=12, accessor_offset=0):
        return {
            "accessors": [
                {
                    "bufferView": buffer_view,
                    "componentType": 5126,
                    "type": "VEC3",
                    "count": 1,
                    "byteOffset": accessor_offset,
                }
            ],
            "bufferViews": [
                {"buffer": 0, "byteOffset": view_offset, "byteLength": view_length}
            ],
        }

    def test_valid_accessor_reads_inside_declared_view(self):
        data = np.asarray([[1.0, 2.0, 3.0]], dtype="<f4").tobytes()
        value = runtime._glb_accessor_array(self._doc(), data, 0)
        np.testing.assert_array_equal(value, [[1.0, 2.0, 3.0]])

    def test_non_integer_buffer_view_index_is_rejected_cleanly(self):
        with self.assertRaisesRegex(RuntimeError, "invalid GLB bufferView index"):
            runtime._glb_accessor_array(self._doc(buffer_view="not-an-index"), bytes(12), 0)

    def test_negative_buffer_view_index_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "invalid GLB bufferView index"):
            runtime._glb_accessor_array(self._doc(buffer_view=-1), bytes(12), 0)

    def test_accessor_cannot_read_past_declared_buffer_view(self):
        # The BIN chunk is large enough, but the accessor starts beyond its own view.
        with self.assertRaisesRegex(RuntimeError, "outside its bufferView"):
            runtime._glb_accessor_array(
                self._doc(view_length=12, accessor_offset=12), bytes(24), 0
            )

    def test_buffer_view_cannot_extend_past_bin_chunk(self):
        with self.assertRaisesRegex(RuntimeError, "bufferView extends outside BIN chunk"):
            runtime._glb_accessor_array(self._doc(view_offset=8, view_length=12), bytes(16), 0)


if __name__ == "__main__":
    unittest.main()
