from __future__ import annotations

import unittest
from pathlib import Path

from modal_3d.deployment import deployment_manifest
from modal_3d.operations import (
    input_mimes_for,
    options_for,
    required_inputs_for,
    required_roles_for,
    validate_input_names,
    worker_for,
)


class Hunyuan2MVContractTests(unittest.TestCase):
    def test_multiview_operation_routes_to_dedicated_worker(self):
        self.assertEqual(worker_for("multiview_to_3d"), "modal-3d-hunyuan2mv")
        self.assertEqual(
            required_roles_for("multiview_to_3d"),
            ["primary-glb", "quality-report"],
        )

    def test_front_is_required_and_other_official_views_are_optional(self):
        self.assertEqual(
            required_inputs_for("multiview_to_3d"),
            ["front"],
        )
        self.assertEqual(
            input_mimes_for("multiview_to_3d"),
            {
                "front": "image/png",
                "back": "image/png",
                "left": "image/png",
                "right": "image/png",
            },
        )
        self.assertEqual(
            set(validate_input_names("multiview_to_3d", {"front": {}})),
            {"front"},
        )
        self.assertEqual(
            set(
                validate_input_names(
                    "multiview_to_3d",
                    {"front": {}, "left": {}, "back": {}, "right": {}},
                )
            ),
            {"front", "left", "back", "right"},
        )
        with self.assertRaisesRegex(ValueError, "missing inputs"):
            validate_input_names("multiview_to_3d", {"left": {}})
        with self.assertRaisesRegex(ValueError, "unknown inputs"):
            validate_input_names(
                "multiview_to_3d",
                {"front": {}, "top": {}},
            )

    def test_full_quality_defaults_follow_official_multiview_example(self):
        self.assertEqual(
            options_for("multiview_to_3d"),
            {
                "seed": 12345,
                "num_inference_steps": 50,
                "guidance_scale": 5.0,
                "octree_resolution": 380,
                "num_chunks": 20000,
            },
        )

    def test_deployment_manifest_tracks_pinned_model_files(self):
        target = next(
            row
            for row in deployment_manifest()["targets"]
            if row["app"] == "modal-3d-hunyuan2mv"
        )
        self.assertEqual(target["module"], "modal_3d.hunyuan2mv_worker")
        self.assertEqual(target["models"], ["multiview_to_3d"])
        self.assertEqual(
            target["weights"][0]["requiredPaths"],
            [
                "Hunyuan3D-2mv/hunyuan3d-dit-v2-mv/config.yaml",
                "Hunyuan3D-2mv/hunyuan3d-dit-v2-mv/model.fp16.safetensors",
            ],
        )

    def test_worker_pins_official_source_and_model_revision(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "modal_3d"
            / "hunyuan2mv_worker.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'SOURCE_REVISION = "f8db63096c8282cb27354314d896feba5ba6ff8a"',
            source,
        )
        self.assertIn(
            'MODEL_REVISION = "3a761b539b29fe4ff64714813aa9560fd66f5de0"',
            source,
        )
        self.assertIn('SUBFOLDER = "hunyuan3d-dit-v2-mv"', source)
        self.assertNotIn("enable_flashvdm()", source)


if __name__ == "__main__":
    unittest.main()
