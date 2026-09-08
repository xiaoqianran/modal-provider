from __future__ import annotations

import unittest

from modal_3d.gpu_telemetry import _percentile, _summary


class GpuTelemetrySummaryTests(unittest.TestCase):
    def test_percentile_interpolates(self):
        self.assertEqual(_percentile([], 0.5), None)
        self.assertEqual(_percentile([10.0], 0.5), 10.0)
        self.assertEqual(_percentile([0.0, 100.0], 0.5), 50.0)

    def test_summary_reports_compute_memory_power_and_clock(self):
        samples = [
            {
                "gpu_util_pct": 20,
                "memory_util_pct": 30,
                "vram_mib": 1024,
                "power_w": 100,
                "sm_clock_mhz": 1200,
            },
            {
                "gpu_util_pct": 80,
                "memory_util_pct": 70,
                "vram_mib": 4096,
                "power_w": 300,
                "sm_clock_mhz": 1800,
            },
        ]
        result = _summary(samples)
        self.assertEqual(result["samples"], 2)
        self.assertEqual(result["gpu_util_avg_pct"], 50.0)
        self.assertEqual(result["gpu_util_p50_pct"], 50.0)
        self.assertEqual(result["gpu_util_max_pct"], 80.0)
        self.assertEqual(result["memory_util_avg_pct"], 50.0)
        self.assertEqual(result["peak_vram_gb"], 4.0)
        self.assertEqual(result["power_avg_w"], 200.0)
        self.assertEqual(result["power_max_w"], 300.0)
        self.assertEqual(result["sm_clock_avg_mhz"], 1500.0)

    def test_summary_tolerates_missing_optional_metrics(self):
        result = _summary([{"gpu_util_pct": 40, "vram_mib": 2048}])
        self.assertEqual(result["gpu_util_avg_pct"], 40.0)
        self.assertEqual(result["peak_vram_gb"], 2.0)
        self.assertIsNone(result["power_avg_w"])
        self.assertIsNone(result["sm_clock_avg_mhz"])


if __name__ == "__main__":
    unittest.main()
