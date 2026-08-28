from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from modal_3d.fastsam3d_plus_plus import CAPABILITY as FASTSAM
from modal_3d.hermit_trellis2_plus_plus import CAPABILITY as HERMIT
from modal_3d.hunyuan2_1_plus_plus import CAPABILITY as HUNYUAN
from modal_3d.pixal3d import CAPABILITY as PIXAL
from scripts.benchmark_runner import (
    Scene,
    assert_deployed_matches,
    build_plan,
    load_manifest,
    validate_budget,
)
from tests.test_canonical_contract import rgba_png


class BenchmarkGuardrailTests(unittest.TestCase):
    def test_black_rgb_benchmark_input_is_rejected_before_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = root / "black.png"
            image.write_bytes(rgba_png(foreground_rgb=(0, 0, 0)))
            manifest = root / "manifest.json"
            import hashlib
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            manifest.write_text(
                json.dumps(
                    {
                        "scenes": [
                            {
                                "id": "black",
                                "canonical": "black.png",
                                "modal_path": f"client-inputs/{digest}.png",
                            }
                        ]
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "too little information"):
                load_manifest(manifest)

    def test_default_smoke_plan_is_four_calls(self) -> None:
        scenes = [Scene("a", Path("/tmp/a.png"), "client-inputs/" + "a" * 64 + ".png", "a" * 64)]
        capabilities = [FASTSAM, HUNYUAN, HERMIT, PIXAL]
        plan = build_plan(capabilities, scenes, [c["id"] for c in capabilities], full=False)
        self.assertEqual(plan["total_calls"], 4)
        validate_budget(plan, max_calls=4, max_estimated_gpu_seconds=1500)

    def test_full_matrix_requires_explicit_budget_increase(self) -> None:
        scenes = [Scene(str(i), Path(f"/tmp/{i}.png"), "client-inputs/" + f"{i:064x}" + ".png", f"{i:064x}") for i in range(5)]
        capabilities = [FASTSAM, HUNYUAN, HERMIT, PIXAL]
        plan = build_plan(capabilities, scenes, [c["id"] for c in capabilities], full=True)
        self.assertEqual(plan["total_calls"], 20)
        with self.assertRaisesRegex(ValueError, "max-calls"):
            validate_budget(plan, max_calls=4, max_estimated_gpu_seconds=10000)
        with self.assertRaisesRegex(ValueError, "GPU seconds"):
            validate_budget(plan, max_calls=20, max_estimated_gpu_seconds=1500)

    def test_execute_preflight_rejects_deployment_or_profile_drift(self) -> None:
        deployed = deepcopy(HUNYUAN)
        deployed["profiles"][0]["options"]["paint_remesh"] = False
        with self.assertRaisesRegex(ValueError, "recommended profile"):
            assert_deployed_matches(HUNYUAN, deployed)

        deployed = deepcopy(HUNYUAN)
        deployed["deployment"]["source_revision"] = "other"
        with self.assertRaisesRegex(ValueError, "deployment"):
            assert_deployed_matches(HUNYUAN, deployed)

        deployed = deepcopy(HUNYUAN)
        deployed["options"]["num_inference_steps"]["maximum"] = 1000
        with self.assertRaisesRegex(ValueError, "options"):
            assert_deployed_matches(HUNYUAN, deployed)

class InterruptedSubmissionTests(unittest.TestCase):
    """A spawned-but-unpersisted call can no longer be re-found in the cloud."""

    def test_unresolved_intent_is_reported_instead_of_guessed(self) -> None:
        from scripts.run_pages_benchmark import _recover_submission

        with self.assertRaisesRegex(RuntimeError, "interrupted before its FunctionCall id"):
            _recover_submission("pixal3d", {"status": "submitting", "intent_at": 1.0})

    def test_resolved_states_are_not_treated_as_submissions(self) -> None:
        from scripts.run_pages_benchmark import _recover_submission

        self.assertFalse(_recover_submission("pixal3d", {"status": "submitted"}))
        self.assertFalse(_recover_submission("pixal3d", {"status": "completed"}))


class LowInformationOverrideTests(unittest.TestCase):
    def test_manifest_can_explicitly_allow_reviewed_black_subject(self) -> None:
        import hashlib
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = root / "black.png"
            image.write_bytes(rgba_png(foreground_rgb=(0, 0, 0)))
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"scenes": [{
                "id": "black",
                "canonical": "black.png",
                "modal_path": f"client-inputs/{digest}.png",
                "allow_low_information": True,
            }]}))
            scenes = load_manifest(manifest)
            self.assertEqual(scenes[0].sha256, digest)
