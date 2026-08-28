from __future__ import annotations

import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from modal_3d import router
from modal_3d.capabilities import (
    CONTRACT,
    assert_routable,
    capabilities_document,
    has_current_adapter_revision,
    profile_options,
    validate_capability,
    validate_options,
    worker_app,
)
from modal_3d.common import WORKER_ADAPTER_REVISION
from modal_3d.fastsam3d_plus_plus import CAPABILITY as FASTSAM3D
from modal_3d.hermit_trellis2_plus_plus import CAPABILITY as TRELLIS2
from modal_3d.hunyuan2_1_plus_plus import CAPABILITY as HUNYUAN
from modal_3d.pixal3d import CAPABILITY as PIXAL3D


class CapabilityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.models = [FASTSAM3D, TRELLIS2, HUNYUAN, PIXAL3D]

    def test_contract_is_json_serializable(self) -> None:
        encoded = json.dumps(capabilities_document(self.models), sort_keys=True)
        self.assertIn(CONTRACT, encoded)

    def test_generation_contract_requires_client_prepared_canonical_inputs(self) -> None:
        document = capabilities_document(self.models)
        generation = document["generation"]
        self.assertNotIn("sam", document)
        self.assertNotIn("app", generation)
        self.assertNotIn("submit_function", generation)
        self.assertNotIn("http", generation)
        self.assertEqual(generation["job_transport"], "modal.FunctionCall")
        self.assertEqual(generation["entrypoint"], "direct_class_method")
        self.assertEqual(generation["input_path_prefix"], "client-inputs/")
        self.assertEqual(
            generation["input_contract"],
            {
                "role": "canonical_rgba",
                "mime": "image/png",
                "mode": "RGBA",
                "width": 1024,
                "height": 1024,
                "bit_depth": 8,
                "layout": "letterbox",
                "alpha": "channel_required",
            },
        )
        self.assertTrue(all(model["input"] == generation["input_contract"] for model in document["models"]))

    def test_contract_has_exact_current_models(self) -> None:
        document = capabilities_document(self.models)
        self.assertEqual(document["contract"], CONTRACT)
        self.assertEqual(
            [model["id"] for model in document["models"]],
            [
                "fastsam3d-plus-plus",
                "hermit-trellis2-plus-plus",
                "hunyuan2.1-plus-plus",
                "pixal3d",
            ],
        )
        self.assertTrue(all(model["status"] == "enabled" for model in document["models"]))

    def test_new_model_is_discovered_without_gateway_changes(self) -> None:
        fifth = deepcopy(FASTSAM3D)
        fifth.update(
            {"id": "new-model", "name": "New", "worker_app": "modal-3d-new", "priority": 50}
        )
        models = [FASTSAM3D, fifth]
        # A new model needs a matching routing-table entry; nothing else changes
        # because there is no gateway and no registry to teach about it.
        with patch.dict(router.WORKERS, {"new-model": ("modal-3d-new", "Model", "generate_job")}):
            self.assertEqual(
                [model["id"] for model in capabilities_document(models)["models"]],
                ["fastsam3d-plus-plus", "new-model"],
            )
            self.assertEqual(worker_app("new-model", models), "modal-3d-new")

    def test_new_model_without_a_routing_entry_is_rejected(self) -> None:
        orphan = deepcopy(FASTSAM3D)
        orphan.update({"id": "new-model", "name": "New", "worker_app": "modal-3d-new"})
        with self.assertRaisesRegex(ValueError, "routing table"):
            assert_routable([FASTSAM3D, orphan])

    def test_worker_app_mismatch_is_rejected(self) -> None:
        drifted = deepcopy(PIXAL3D)
        drifted["worker_app"] = "modal-3d-pixal3d-v2"
        with self.assertRaisesRegex(ValueError, "routing table"):
            assert_routable([drifted])

    def test_entrypoint_mismatch_is_rejected(self) -> None:
        drifted = deepcopy(PIXAL3D)
        drifted["generation_entrypoint"] = {
            "kind": "class_method",
            "class_name": "Model",
            "method_name": "generate",
        }
        with self.assertRaisesRegex(ValueError, "routing table"):
            assert_routable([drifted])

    def test_recommended_profiles_match_verified_client_baseline(self) -> None:
        self.assertEqual(
            profile_options("fastsam3d-plus-plus", "recommended", self.models),
            {"dmd_interval": 1, "dmd_history": 5},
        )
        self.assertEqual(
            profile_options("hermit-trellis2-plus-plus", "recommended", self.models),
            {"pipeline_type": "1536_cascade", "acceleration": "base", "texture_size": 4096},
        )
        self.assertEqual(
            profile_options("hunyuan2.1-plus-plus", "recommended", self.models),
            {"acceleration": "base", "interval": 1, "history": 6, "num_inference_steps": 50, "paint_remesh": True},
        )
        self.assertEqual(
            profile_options("pixal3d", "recommended", self.models),
            {
                "fov": None,
                "pipeline_type": "1536_cascade",
                "max_num_tokens": 49152,
                "texture_size": 4096,
            },
        )

    def test_recommended_profiles_declare_quality_and_provenance(self) -> None:
        expected_tiers = {
            "fastsam3d-plus-plus": "accelerated",
            "hermit-trellis2-plus-plus": "full_quality",
            "hunyuan2.1-plus-plus": "full_quality",
            "pixal3d": "full_quality",
        }
        for capability in (FASTSAM3D, TRELLIS2, HUNYUAN, PIXAL3D):
            profile = capability["profiles"][0]
            self.assertEqual(profile["quality"]["tier"], expected_tiers[capability["id"]])
            self.assertIn(profile["quality"]["verification"]["status"], {"verified", "stale"})
            self.assertIn("benchmark", capability["reference"])
            self.assertIn("status", capability["reference"])

    def test_fastsam_sampler_metadata_matches_accelerated_configs(self) -> None:
        sampler = FASTSAM3D["profiles"][0]["quality"]["sampler"]
        self.assertEqual(sampler["runtime_ss_steps"], 25)
        self.assertEqual(sampler["runtime_slat_steps"], 25)
        self.assertEqual(sampler["generator_config_ss_steps"], 2)
        self.assertEqual(sampler["generator_config_slat_steps"], 12)
        self.assertEqual(sampler["ss_cache_stride"], 3)
        self.assertEqual(sampler["slat_carving_ratio"], 0.1)

    def test_fastsam_dmd_controls_are_bounded(self) -> None:
        options = FASTSAM3D["options"]
        self.assertEqual(options["seed"]["minimum"], 0)
        self.assertEqual(options["seed"]["maximum"], 4294967295)
        self.assertEqual(options["dmd_interval"]["minimum"], 1)
        self.assertEqual(options["dmd_interval"]["maximum"], 12)
        self.assertEqual(options["dmd_history"]["minimum"], 4)
        self.assertEqual(options["dmd_history"]["maximum"], 25)

    def test_hunyuan_full_quality_defaults_are_bounded(self) -> None:
        options = HUNYUAN["options"]
        self.assertEqual(options["paint_remesh"]["default"], True)
        self.assertEqual(options["interval"]["default"], 1)
        self.assertEqual(options["interval"]["maximum"], 12)
        self.assertEqual(options["history"]["maximum"], 32)
        self.assertEqual(options["num_inference_steps"]["maximum"], 100)
        self.assertEqual(HUNYUAN["profiles"][0]["quality"]["verification"]["status"], "verified")
        self.assertEqual(HUNYUAN["reference"]["status"], "stale")
        self.assertGreater(HUNYUAN["reference"]["warm_seconds"], 500)

    def test_worker_lookup_is_part_of_same_contract(self) -> None:
        self.assertEqual(worker_app("fastsam3d-plus-plus", self.models), "modal-3d-fastsam3d")
        self.assertEqual(worker_app("pixal3d", self.models), "modal-3d-pixal3d")

    def test_worker_manifest_carries_current_adapter_revision(self) -> None:
        for capability in (FASTSAM3D, TRELLIS2, HUNYUAN, PIXAL3D):
            self.assertTrue(has_current_adapter_revision(capability))
            self.assertEqual(
                capability["deployment"]["adapter_revision"],
                WORKER_ADAPTER_REVISION,
            )

    def test_stale_worker_is_not_advertised_or_routable(self) -> None:
        stale = deepcopy(HUNYUAN)
        stale["deployment"]["adapter_revision"] = "modal-3d.worker-adapter.v1"
        models = [FASTSAM3D, stale]
        self.assertEqual(
            [model["id"] for model in capabilities_document(models)["models"]],
            ["fastsam3d-plus-plus"],
        )
        with self.assertRaisesRegex(ValueError, "stale; redeploy required"):
            worker_app("hunyuan2.1-plus-plus", models)

    def test_capability_document_is_not_mutable_global_state(self) -> None:
        first = capabilities_document(self.models)
        first["models"][0]["name"] = "mutated"
        self.assertNotEqual(capabilities_document(self.models)["models"][0]["name"], "mutated")

    def test_unknown_model_and_profile_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown model"):
            worker_app("missing", self.models)
        with self.assertRaisesRegex(ValueError, "does not support profile"):
            profile_options("pixal3d", "quality", self.models)

    def test_routing_entrypoint_is_published_to_clients(self) -> None:
        document = capabilities_document(self.models)
        for model in document["models"]:
            with self.subTest(model=model["id"]):
                self.assertEqual(
                    model["generation_entrypoint"],
                    {"kind": "class_method", "class_name": "Model", "method_name": "generate_job"},
                )

    def test_invalid_generation_entrypoint_is_rejected(self) -> None:
        invalid = deepcopy(FASTSAM3D)
        invalid["generation_entrypoint"] = {"kind": "class_method", "class_name": "Model"}
        with self.assertRaisesRegex(ValueError, "method_name"):
            validate_capability(invalid)

    def test_invalid_manifest_is_rejected_before_registration(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing fields"):
            validate_capability({"id": "incomplete"})

    def test_options_must_be_mapping(self) -> None:
        with self.assertRaisesRegex(TypeError, "options must be an object"):
            validate_options("pixal3d", ["seed", 1], self.models)  # type: ignore[arg-type]

    def test_unknown_option_is_rejected_before_worker(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown options"):
            validate_options("pixal3d", {"does_not_exist": 1}, self.models)

    def test_option_types_are_strict(self) -> None:
        with self.assertRaisesRegex(ValueError, "seed must be integer"):
            validate_options("fastsam3d-plus-plus", {"seed": True}, self.models)
        with self.assertRaisesRegex(ValueError, "fov must be number"):
            validate_options("pixal3d", {"fov": "35"}, self.models)
        self.assertEqual(
            validate_options("pixal3d", {"fov": None}, self.models),
            {"fov": None},
        )
        with self.assertRaisesRegex(ValueError, "must be one of"):
            validate_options("pixal3d", {"pipeline_type": "2048_cascade"}, self.models)
        with self.assertRaisesRegex(ValueError, "pipeline_type must be string"):
            validate_options("pixal3d", {"pipeline_type": 1536}, self.models)

    def test_existing_worker_ranges_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "interval must be >= 1"):
            validate_options("hunyuan2.1-plus-plus", {"interval": 0}, self.models)
        with self.assertRaisesRegex(ValueError, "history must be >= 4"):
            validate_options("hunyuan2.1-plus-plus", {"history": 3}, self.models)
        with self.assertRaisesRegex(ValueError, "num_inference_steps must be <= 100"):
            validate_options("hunyuan2.1-plus-plus", {"num_inference_steps": 101}, self.models)
        with self.assertRaisesRegex(ValueError, "interval must be <= 12"):
            validate_options("hunyuan2.1-plus-plus", {"interval": 13}, self.models)

    def test_valid_options_are_preserved_without_inventing_defaults(self) -> None:
        options = {"seed": 7, "interval": 3, "history": 6, "num_inference_steps": 50}
        self.assertEqual(validate_options("hunyuan2.1-plus-plus", options, self.models), options)
        self.assertEqual(validate_options("hermit-trellis2-plus-plus", None, self.models), {})


if __name__ == "__main__":
    unittest.main()
