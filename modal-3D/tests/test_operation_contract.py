from __future__ import annotations

import unittest
from unittest.mock import patch

from modal_3d import router
from modal_3d.capabilities import OPERATION_CONTRACT, capabilities_document, validate_capability
from modal_3d.common import (
    GLB_ARTIFACT,
    input_descriptor,
    operation_capability,
    output_descriptor,
)
from modal_3d.fastsam3d_plus_plus import CAPABILITY as FASTSAM3D
from modal_3d.operations import (
    capabilities as operation_capabilities,
)
from modal_3d.operations import (
    required_roles_for,
    revision_for,
    worker_for,
)


class OperationContractTests(unittest.TestCase):
    def test_segment_parts_uses_dedicated_gpu_worker_and_partset_roles(self):
        capability = next(
            item for item in operation_capabilities() if item["id"] == "segment_parts"
        )
        self.assertEqual(worker_for("segment_parts"), "modal-3d-p3sam")
        self.assertEqual(capability["worker_app"], "modal-3d-p3sam")
        self.assertEqual(capability["execution"]["resource"], "gpu")
        self.assertEqual(capability["revision"], revision_for("segment_parts"))
        self.assertEqual(
            required_roles_for("segment_parts"),
            ["primary-glb", "parts-manifest", "face-labels", "quality-report"],
        )

    def test_complete_parts_uses_xpart_and_assembly_roles(self):
        capability = next(
            item for item in operation_capabilities() if item["id"] == "complete_parts"
        )
        self.assertEqual(worker_for("complete_parts"), "modal-3d-xpart")
        self.assertEqual(capability["worker_app"], "modal-3d-xpart")
        self.assertEqual(capability["execution"]["resource"], "gpu")
        self.assertEqual(capability["revision"], revision_for("complete_parts"))
        self.assertEqual(
            capability["inputs"], ["asset", "parts_manifest", "face_labels"]
        )
        self.assertEqual(
            required_roles_for("complete_parts"),
            ["primary-glb", "assembly-preview", "quality-report"],
        )

    def test_existing_generation_worker_keeps_legacy_contract_and_gains_operation_shape(self):
        validated = validate_capability(FASTSAM3D)
        self.assertEqual(validated["operation"], "image_to_3d")
        self.assertEqual(validated["inputs"][0]["kind"], "image")
        self.assertEqual(validated["inputs"][0]["contract"], validated["input"])
        self.assertEqual(validated["outputs"][0]["kind"], "textured_mesh")
        self.assertEqual(validated["entrypoint"], validated["generation_entrypoint"])
        self.assertEqual(validated["output"], "textured")

    def test_document_publishes_additive_operation_contract_without_breaking_v3_generation(self):
        document = capabilities_document([FASTSAM3D])
        self.assertEqual(document["contract"], "modal-3d.capabilities.v3")
        self.assertEqual(document["operations"]["contract"], OPERATION_CONTRACT)
        self.assertEqual(document["models"][0]["id"], "fastsam3d-plus-plus")
        self.assertEqual(document["capabilities"][0]["id"], "fastsam3d-plus-plus")
        self.assertEqual(
            document["generation"]["input_contract"],
            document["models"][0]["input"],
        )

    def test_non_image_mesh_operation_does_not_need_fake_generation_fields(self):
        capability = operation_capability(
            "p3-sam",
            "P3-SAM",
            "modal-3d-p3sam",
            "Semantic 3D part segmentation",
            "segment_parts",
            [input_descriptor("asset", "mesh", artifact=GLB_ARTIFACT)],
            [
                output_descriptor(
                    "parts",
                    "part_set",
                    artifact={"mime": "application/json", "extension": ".json"},
                )
            ],
            {},
            warm_seconds=1.0,
            entrypoint={
                "kind": "class_method",
                "class_name": "Model",
                "method_name": "run_job",
            },
        )
        validated = validate_capability(capability)
        self.assertEqual(validated["operation"], "segment_parts")
        self.assertEqual(validated["inputs"][0]["kind"], "mesh")
        self.assertEqual(validated["outputs"][0]["kind"], "part_set")
        self.assertNotIn("input", validated)
        self.assertNotIn("output", validated)
        self.assertNotIn("generation_entrypoint", validated)

    def test_generic_route_can_use_non_generation_method_and_existing_artifact(self):
        class FakeMethod:
            def __init__(self):
                self.calls = []

            def spawn(self, *args):
                self.calls.append(args)
                return "fc-operation"

        class FakeObject:
            def __init__(self, method):
                self.run_job = method

        class FakeCls:
            def __init__(self, method):
                self.method = method

            def __call__(self):
                return FakeObject(self.method)

        method = FakeMethod()
        route = ("modal-3d-p3sam", "Model", "run_job")
        with (
            patch.dict(router.ROUTES, {"p3-sam": route}),
            patch.object(router.modal.Cls, "from_name", return_value=FakeCls(method)) as lookup,
        ):
            call = router.spawn_operation(
                "p3-sam",
                {"asset": "fastsam3d-plus-plus/example.glb"},
                {"semantic": True},
            )

        self.assertEqual(lookup.call_args.args, ("modal-3d-p3sam", "Model"))
        self.assertEqual(
            method.calls,
            [({"asset": "fastsam3d-plus-plus/example.glb"}, {"semantic": True})],
        )
        self.assertEqual(call, "fc-operation")

    def test_generic_operation_key_separates_operation_semantics(self):
        inputs = {"asset": "fastsam3d-plus-plus/example.glb"}
        first = router.operation_job_key("tool", "segment_parts", inputs, {})
        second = router.operation_job_key("tool", "retopology", inputs, {})
        self.assertNotEqual(first, second)

    def test_operation_inputs_support_multiple_named_artifacts(self):
        inputs = {
            "asset": "assets/mesh.glb",
            "mask": "masks/edit.png",
        }
        self.assertEqual(router.normalize_operation_inputs(inputs), inputs)

    def test_operation_input_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            router.spawn_operation("p3-sam", {"asset": "../private.glb"}, {})


if __name__ == "__main__":
    unittest.main()
