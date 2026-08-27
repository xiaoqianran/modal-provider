from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modal_3d.fastsam3d_plus_plus import CAPABILITY as FASTSAM
from modal_3d.hunyuan2_1_plus_plus import CAPABILITY as HUNYUAN
from scripts.benchmark_runner import Scene
from scripts.run_pages_benchmark import _new_full_state, _validated_smoke_state


class BenchmarkStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenes = [
            Scene("smoke", Path("/tmp/smoke.png"), "client-inputs/" + "a" * 64 + ".png", "a" * 64),
            Scene("next", Path("/tmp/next.png"), "client-inputs/" + "b" * 64 + ".png", "b" * 64),
        ]
        self.models = [FASTSAM["id"], HUNYUAN["id"]]
        self.capabilities = {FASTSAM["id"]: FASTSAM, HUNYUAN["id"]: HUNYUAN}

    def smoke_document(self) -> dict:
        return {
            "schema": "modal-3d.benchmark-smoke.v1",
            "models": {
                model_id: {
                    "status": "completed",
                    "scene": "smoke",
                    "modal_path": self.scenes[0].modal_path,
                    "input_sha256": self.scenes[0].sha256,
                    "task_id": f"fc-{index}",
                    "options": capability["profiles"][0]["options"],
                    "result": {"model": model_id, "artifact": {"bytes": 1}},
                }
                for index, (model_id, capability) in enumerate(self.capabilities.items())
            },
        }

    def test_full_state_reuses_smoke_instead_of_resubmitting_scene_zero(self) -> None:
        smoke = self.smoke_document()
        state = _new_full_state({"mode": "full"}, smoke, self.scenes, self.models)
        for model_id in self.models:
            model = state["models"][model_id]
            self.assertEqual(model["status"], "ready")
            self.assertEqual(model["next_scene_index"], 1)
            self.assertEqual([item["scene"] for item in model["results"]], ["smoke"])

    def test_failed_smoke_blocks_full_initialization(self) -> None:
        smoke = self.smoke_document()
        smoke["models"][FASTSAM["id"]]["status"] = "failed"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "smoke.json"
            path.write_text(json.dumps(smoke))
            with self.assertRaisesRegex(ValueError, "completed successfully"):
                _validated_smoke_state(path, self.scenes, self.capabilities, self.models)

    def test_profile_drift_blocks_full_initialization(self) -> None:
        smoke = self.smoke_document()
        smoke["models"][HUNYUAN["id"]]["options"] = {"num_inference_steps": 1}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "smoke.json"
            path.write_text(json.dumps(smoke))
            with self.assertRaisesRegex(ValueError, "recommended profile"):
                _validated_smoke_state(path, self.scenes, self.capabilities, self.models)
