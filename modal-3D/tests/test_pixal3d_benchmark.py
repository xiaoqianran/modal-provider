from __future__ import annotations

import unittest

from modal_3d.pixal3d_benchmark import (
    FROZEN_QUALITY_OPTIONS,
    get_variant,
    summarize_runs,
    validate_warmup,
)


class Pixal3DBenchmarkTests(unittest.TestCase):
    def test_allocator_variants_keep_quality_frozen(self) -> None:
        self.assertEqual(FROZEN_QUALITY_OPTIONS["pipeline_type"], "1536_cascade")
        self.assertEqual(FROZEN_QUALITY_OPTIONS["max_num_tokens"], 49152)
        self.assertEqual(FROZEN_QUALITY_OPTIONS["texture_size"], 4096)
        self.assertEqual(FROZEN_QUALITY_OPTIONS["seed"], 42)

        official = get_variant("sdpa-official")
        optimized = get_variant("sdpa-no-stage-empty-cache")
        self.assertEqual(official.attention_backend, optimized.attention_backend)
        self.assertFalse(official.suppress_stage_empty_cache)
        self.assertTrue(optimized.suppress_stage_empty_cache)

    def test_unreleased_fa2_variant_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "gated"):
            get_variant("fa2-official")
        variant = get_variant("fa2-official", allow_unreleased=True)
        self.assertEqual(variant.attention_backend, "flash_attn")
        self.assertIsNotNone(variant.requires_artifact)

    def test_warmup_validation_detects_backend_or_allocator_mismatch(self) -> None:
        variant = get_variant("sdpa-no-stage-empty-cache")
        validate_warmup(
            variant,
            {"attention_backend": "sdpa", "stage_empty_cache_suppressed": True},
        )
        with self.assertRaisesRegex(RuntimeError, "backend mismatch"):
            validate_warmup(
                variant,
                {"attention_backend": "flash_attn", "stage_empty_cache_suppressed": True},
            )
        with self.assertRaisesRegex(RuntimeError, "allocator-gate mismatch"):
            validate_warmup(
                variant,
                {"attention_backend": "sdpa", "stage_empty_cache_suppressed": False},
            )

    def test_summary_uses_nested_normalized_metrics(self) -> None:
        records = [
            {
                "client_e2e_s": 10.0,
                "result": {
                    "timing": {"inference_s": 7.0},
                    "metrics": {
                        "peak_vram_gb": 31.0,
                        "timings": {
                            "worker_total_s": 9.0,
                            "pipeline_s": 4.0,
                            "glb_postprocess_s": 2.0,
                            "glb_export_s": 1.0,
                        },
                    },
                },
            },
            {
                "client_e2e_s": 12.0,
                "result": {
                    "timing": {"inference_s": 9.0},
                    "metrics": {
                        "peak_vram_gb": 33.0,
                        "timings": {
                            "worker_total_s": 11.0,
                            "pipeline_s": 6.0,
                            "glb_postprocess_s": 3.0,
                            "glb_export_s": 1.0,
                        },
                    },
                },
            },
        ]
        summary = summarize_runs(records)
        self.assertEqual(summary["client_e2e_median_s"], 11.0)
        self.assertEqual(summary["worker_total_median_s"], 10.0)
        self.assertEqual(summary["pipeline_median_s"], 5.0)
        self.assertEqual(summary["glb_postprocess_median_s"], 2.5)
        self.assertEqual(summary["peak_vram_max_gb"], 33.0)


if __name__ == "__main__":
    unittest.main()
