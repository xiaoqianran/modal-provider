from __future__ import annotations

import unittest

from modal_3d.hunyuan_benchmark import (
    FROZEN_QUALITY_OPTIONS,
    get_variant,
    summarize_runs,
    validate_warmup,
)


class HunyuanBenchmarkTests(unittest.TestCase):
    def test_variants_keep_full_quality_request_frozen(self) -> None:
        self.assertEqual(FROZEN_QUALITY_OPTIONS["acceleration"], "base")
        self.assertEqual(FROZEN_QUALITY_OPTIONS["num_inference_steps"], 50)
        self.assertTrue(FROZEN_QUALITY_OPTIONS["paint_remesh"])

        base = get_variant("base-official")
        flash = get_variant("flashvdm-decoder")
        self.assertFalse(base.flashvdm)
        self.assertTrue(flash.flashvdm)
        self.assertFalse(flash.sageattention)

    def test_sageattention_is_quality_gated(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "gated"):
            get_variant("sageattention")
        variant = get_variant("sageattention", allow_unreleased=True)
        self.assertTrue(variant.sageattention)
        self.assertIsNotNone(variant.requires_artifact)

    def test_warmup_validation(self) -> None:
        variant = get_variant("flashvdm-compile")
        validate_warmup(
            variant,
            {
                "runtime_acceleration": {
                    "flashvdm": True,
                    "torch_compile": True,
                    "sageattention": False,
                }
            },
        )
        with self.assertRaisesRegex(RuntimeError, "mismatch"):
            validate_warmup(
                variant,
                {
                    "runtime_acceleration": {
                        "flashvdm": False,
                        "torch_compile": True,
                        "sageattention": False,
                    }
                },
            )

    def test_summary_keeps_shape_and_paint_separate(self) -> None:
        records = [
            {
                "client_e2e_s": 80.0,
                "result": {
                    "timing": {"inference_s": 70.0},
                    "metrics": {
                        "shape_s": 20.0,
                        "paint_s": 50.0,
                        "peak_vram_allocated_gb": 22.0,
                    },
                },
            },
            {
                "client_e2e_s": 84.0,
                "result": {
                    "timing": {"inference_s": 74.0},
                    "metrics": {
                        "shape_s": 24.0,
                        "paint_s": 50.0,
                        "peak_vram_allocated_gb": 23.0,
                    },
                },
            },
        ]
        summary = summarize_runs(records)
        self.assertEqual(summary["shape_median_s"], 22.0)
        self.assertEqual(summary["paint_median_s"], 50.0)
        self.assertEqual(summary["peak_vram_allocated_max_gb"], 23.0)


if __name__ == "__main__":
    unittest.main()
