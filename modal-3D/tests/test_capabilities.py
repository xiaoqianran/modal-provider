from __future__ import annotations

import json
import unittest
from copy import deepcopy

from modal_3d.capabilities import (
    CONTRACT,
    capabilities_document,
    profile_options,
    validate_capability,
    validate_options,
    worker_app,
)
from modal_3d.fastsam3d_plus_plus import CAPABILITY as FASTSAM3D
from modal_3d.hermit_trellis2_plus_plus import CAPABILITY as TRELLIS2
from modal_3d.hunyuan2_1_plus_plus import CAPABILITY as HUNYUAN
from modal_3d.pixal3d import CAPABILITY as PIXAL3D


class FakeRegistry:
    def __init__(self, values):
        self.values = {item["id"]: deepcopy(item) for item in values}

    def get(self, key, default=None):
        return deepcopy(self.values.get(key, default))

    def items(self):
        return [(key, deepcopy(value)) for key, value in self.values.items()]


class CapabilityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = FakeRegistry([FASTSAM3D, TRELLIS2, HUNYUAN, PIXAL3D])

    def test_contract_is_json_serializable(self) -> None:
        encoded = json.dumps(capabilities_document(self.registry), sort_keys=True)
        self.assertIn(CONTRACT, encoded)

    def test_contract_has_exact_current_models(self) -> None:
        document = capabilities_document(self.registry)
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
        registry = FakeRegistry([FASTSAM3D, fifth])
        self.assertEqual(
            [model["id"] for model in capabilities_document(registry)["models"]],
            ["fastsam3d-plus-plus", "new-model"],
        )
        self.assertEqual(worker_app("new-model", registry), "modal-3d-new")

    def test_recommended_profiles_match_verified_client_baseline(self) -> None:
        self.assertEqual(
            profile_options("fastsam3d-plus-plus", "recommended", self.registry),
            {"dmd_interval": 1, "dmd_history": 5},
        )
        self.assertEqual(
            profile_options("hermit-trellis2-plus-plus", "recommended", self.registry), {}
        )
        self.assertEqual(
            profile_options("hunyuan2.1-plus-plus", "recommended", self.registry),
            {"interval": 3, "history": 6, "num_inference_steps": 50},
        )
        self.assertEqual(profile_options("pixal3d", "recommended", self.registry), {"fov": None})

    def test_worker_lookup_is_part_of_same_contract(self) -> None:
        self.assertEqual(worker_app("fastsam3d-plus-plus", self.registry), "modal-3d-fastsam3d")
        self.assertEqual(worker_app("pixal3d", self.registry), "modal-3d-pixal3d")

    def test_capability_document_is_not_mutable_global_state(self) -> None:
        first = capabilities_document(self.registry)
        first["models"][0]["name"] = "mutated"
        self.assertNotEqual(capabilities_document(self.registry)["models"][0]["name"], "mutated")

    def test_unknown_model_and_profile_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown model"):
            worker_app("missing", self.registry)
        with self.assertRaisesRegex(ValueError, "does not support profile"):
            profile_options("pixal3d", "quality", self.registry)

    def test_invalid_manifest_is_rejected_before_registration(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing fields"):
            validate_capability({"id": "incomplete"})

    def test_options_must_be_mapping(self) -> None:
        with self.assertRaisesRegex(TypeError, "options must be an object"):
            validate_options("pixal3d", ["seed", 1], self.registry)  # type: ignore[arg-type]

    def test_unknown_option_is_rejected_before_worker(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown options"):
            validate_options("pixal3d", {"texture_size": 8192}, self.registry)

    def test_option_types_are_strict(self) -> None:
        with self.assertRaisesRegex(ValueError, "seed must be integer"):
            validate_options("fastsam3d-plus-plus", {"seed": True}, self.registry)
        with self.assertRaisesRegex(ValueError, "fov must be number"):
            validate_options("pixal3d", {"fov": "35"}, self.registry)
        self.assertEqual(
            validate_options("pixal3d", {"fov": None}, self.registry),
            {"fov": None},
        )

    def test_existing_worker_ranges_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "interval must be >= 1"):
            validate_options("hunyuan2.1-plus-plus", {"interval": 0}, self.registry)
        with self.assertRaisesRegex(ValueError, "history must be >= 4"):
            validate_options("hunyuan2.1-plus-plus", {"history": 3}, self.registry)

    def test_valid_options_are_preserved_without_inventing_defaults(self) -> None:
        options = {"seed": 7, "interval": 3, "history": 6, "num_inference_steps": 50}
        self.assertEqual(validate_options("hunyuan2.1-plus-plus", options, self.registry), options)
        self.assertEqual(validate_options("hermit-trellis2-plus-plus", None, self.registry), {})


if __name__ == "__main__":
    unittest.main()
