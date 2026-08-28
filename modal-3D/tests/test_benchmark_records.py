from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from modal_3d.common import validate_canonical_png
from modal_3d.fastsam3d_plus_plus import CAPABILITY as FASTSAM
from modal_3d.hermit_trellis2_plus_plus import CAPABILITY as HERMIT
from modal_3d.hunyuan2_1_plus_plus import CAPABILITY as HUNYUAN
from modal_3d.pixal3d import CAPABILITY as PIXAL
from modal_3d.png import foreground_stats
from scripts.benchmark_runner import load_manifest

ROOT = Path(__file__).resolve().parents[1]
SCENES_PATH = ROOT / "benchmarks/full-quality-scenes-2026-08-28.json"
SMOKE_PATH = ROOT / "benchmarks/full-quality-smoke-2026-08-28.json"
CAPABILITIES = {item["id"]: item for item in (FASTSAM, HUNYUAN, HERMIT, PIXAL)}


class BenchmarkRecordTests(unittest.TestCase):
    def test_fixed_scene_inputs_are_self_consistent(self) -> None:
        document = json.loads(SCENES_PATH.read_text())
        self.assertEqual(document["schema"], "modal-3d.full-quality-scenes.v1")
        self.assertEqual(len(document["scenes"]), 5)
        for scene in document["scenes"]:
            canonical = scene["canonical"]
            path = ROOT / canonical["path"]
            payload = path.read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), canonical["sha256"])
            self.assertEqual(len(payload), canonical["bytes"])
            self.assertEqual(canonical["modal_path"], f"client-inputs/{canonical['sha256']}.png")
            contract = validate_canonical_png(path)
            self.assertEqual(contract["width"], 1024)
            self.assertEqual(contract["height"], 1024)
            stats = foreground_stats(payload, 1024, 1024)
            self.assertGreater(stats["foreground_rgb_nonzero_fraction"], 0.01)

    def test_runner_reads_the_canonical_record_directly(self) -> None:
        scenes = load_manifest(SCENES_PATH)
        self.assertEqual([scene.id for scene in scenes], [
            "scene-biplane",
            "scene-house",
            "scene-lantern",
            "scene-plant",
            "scene-teapot",
        ])
        self.assertTrue(all(scene.canonical.is_file() for scene in scenes))

    def test_smoke_record_matches_current_quality_profiles(self) -> None:
        smoke = json.loads(SMOKE_PATH.read_text())
        scenes = json.loads(SCENES_PATH.read_text())
        self.assertEqual(smoke["schema"], "modal-3d.full-quality-smoke.v1")
        self.assertEqual(set(smoke["models"]), set(CAPABILITIES))
        biplane = next(scene for scene in scenes["scenes"] if scene["id"] == "scene-biplane")
        self.assertEqual(smoke["scene"]["canonical"]["sha256"], biplane["canonical"]["sha256"])

        for model_id, record in smoke["models"].items():
            capability = CAPABILITIES[model_id]
            recommended = next(profile for profile in capability["profiles"] if profile["id"] == "recommended")
            self.assertEqual(record["status"], "passed")
            self.assertEqual(record["options"], recommended["options"])
            self.assertEqual(record["quality"], recommended["quality"])
            # `adapter_revision` is a runtime-contract marker stamped into the
            # manifest, not part of the physical deployment a benchmark ran
            # against. Historical records keep the revision they were taken with.
            self.assertEqual(
                {k: v for k, v in record["deployment"].items() if k != "adapter_revision"},
                {k: v for k, v in capability["deployment"].items() if k != "adapter_revision"},
            )
            self.assertEqual(record["result"]["model"], model_id)
            self.assertEqual(record["result"]["artifact"]["glb_version"], 2)
            self.assertGreater(record["result"]["artifact"]["bytes"], 0)
            self.assertGreater(record["result"]["timing"]["inference_s"], 0)

    def test_smoke_records_full_quality_hunyuan(self) -> None:
        smoke = json.loads(SMOKE_PATH.read_text())
        hunyuan = smoke["models"]["hunyuan2.1-plus-plus"]
        self.assertTrue(hunyuan["options"]["paint_remesh"])
        self.assertEqual(hunyuan["options"]["num_inference_steps"], 50)
        metrics = hunyuan["result"]["metrics"]
        self.assertEqual(metrics["paint_views"], 6)
        self.assertEqual(metrics["paint_resolution"], 512)
        self.assertTrue(metrics["paint_remesh"])
        self.assertGreater(metrics["shape_s"], 0)
        self.assertGreater(metrics["paint_s"], 0)

    def test_smoke_records_runtime_fastsam_steps_as_metadata(self) -> None:
        sampler = FASTSAM["profiles"][0]["quality"]["sampler"]
        self.assertEqual(sampler["runtime_ss_steps"], 25)
        self.assertEqual(sampler["runtime_slat_steps"], 25)
        self.assertEqual(sampler["generator_config_ss_steps"], 2)
        self.assertEqual(sampler["generator_config_slat_steps"], 12)
