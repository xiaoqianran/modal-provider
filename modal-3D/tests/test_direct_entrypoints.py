"""Every worker must expose the same direct GPU entrypoint.

The local client spawns `Model.generate_job` on the model's own Modal App. Any
worker that falls back to an adapter function silently reintroduces a CPU cold
start, so the contract is asserted here rather than discovered on a paid run.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modal_3d import (
    fastsam3d_plus_plus,
    hermit_trellis2_plus_plus,
    hunyuan2_1_plus_plus,
    pixal3d,
    router,
)
from modal_3d.capabilities import assert_routable
from modal_3d.common import run_generation_job
from tests.test_canonical_contract import rgba_png

WORKERS = [
    ("fastsam3d-plus-plus", fastsam3d_plus_plus),
    ("hunyuan2.1-plus-plus", hunyuan2_1_plus_plus),
    ("hermit-trellis2-plus-plus", hermit_trellis2_plus_plus),
    ("pixal3d", pixal3d),
]

EXPECTED_ENTRYPOINT = {
    "kind": "class_method",
    "class_name": "Model",
    "method_name": "generate_job",
}


def glb_bytes(payload: bytes = b"{}") -> bytes:
    body = b"\x00" * ((4 - len(payload) % 4) % 4) + b"JSON" + payload
    chunk = len(payload).to_bytes(4, "little") + body
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunk)) + chunk


class DirectEntrypointContractTests(unittest.TestCase):
    def test_every_worker_declares_the_same_generation_entrypoint(self) -> None:
        for model_id, module in WORKERS:
            with self.subTest(model=model_id):
                self.assertEqual(module.CAPABILITY["id"], model_id)
                self.assertEqual(module.CAPABILITY["generation_entrypoint"], EXPECTED_ENTRYPOINT)

    def test_every_worker_exposes_generate_job_as_a_modal_method(self) -> None:
        # `Model` is a modal.Cls, not a plain class, so assert against source.
        for model_id, module in WORKERS:
            with self.subTest(model=model_id):
                source = Path(module.__file__).read_text(encoding="utf-8")
                self.assertIn("@modal.method()", source)
                self.assertIn("def generate_job(self, input_path: str", source)
                self.assertIn("run_generation_job(", source)
                self.assertIn("self._generate, input_path, options", source)
                self.assertNotIn("self.generate, input_path, options", source)
                self.assertNotIn("def generate(\n", source)

    def test_no_worker_registers_a_cpu_adapter_function(self) -> None:
        for model_id, module in WORKERS:
            with self.subTest(model=model_id):
                source = Path(module.__file__).read_text(encoding="utf-8")
                self.assertNotIn("register_worker_entrypoint", source)
                self.assertNotIn("@modal.concurrent", source)
                self.assertNotIn("add_local_python_source", source)

    def test_routing_table_covers_every_worker(self) -> None:
        capabilities = [module.CAPABILITY for _, module in WORKERS]
        self.assertEqual(sorted(router.WORKERS), sorted(item["id"] for item in capabilities))
        # assert_routable raises on any disagreement between the two.
        assert_routable(capabilities)

    def test_routing_table_matches_declared_worker_apps(self) -> None:
        self.assertEqual(
            router.WORKERS,
            {
                "fastsam3d-plus-plus": ("modal-3d-fastsam3d", "Model", "generate_job"),
                "hunyuan2.1-plus-plus": ("modal-3d-hunyuan", "Model", "generate_job"),
                "hermit-trellis2-plus-plus": (
                    "modal-3d-hermit-trellis2-plus-plus",
                    "Model",
                    "generate_job",
                ),
                "pixal3d": ("modal-3d-pixal3d", "Model", "generate_job"),
            },
        )

    def test_unknown_model_is_rejected_locally(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown model"):
            router.resolve("does-not-exist")

    def test_only_client_inputs_are_routable(self) -> None:
        self.assertEqual(
            router.normalize_input_path("client-inputs/abc.png"), "client-inputs/abc.png"
        )
        for rejected in (
            "source-inputs/source.jpg",
            "/artifacts/client-inputs/abc.png",
            "client-inputs/../secrets.png",
            "sam31/legacy/canonical.png",
        ):
            with self.subTest(path=rejected), self.assertRaises(ValueError):
                router.normalize_input_path(rejected)


class SpawnRoutingTests(unittest.TestCase):
    def test_spawn_targets_the_gpu_class_method_directly(self) -> None:
        class FakeMethod:
            def __init__(self):
                self.calls: list[tuple] = []

            def spawn(self, input_path: str, options: dict):
                self.calls.append((input_path, options))
                return "fc-direct"

        class FakeObject:
            def __init__(self, method):
                self.generate_job = method

        class FakeCls:
            def __init__(self, method):
                self.method = method

            def __call__(self):
                return FakeObject(self.method)

        method = FakeMethod()
        with patch.object(router.modal.Cls, "from_name", return_value=FakeCls(method)) as lookup:
            call = router.spawn_generation("pixal3d", "client-inputs/abc.png", {"seed": 7})
        self.assertEqual(lookup.call_args.args, ("modal-3d-pixal3d", "Model"))
        self.assertEqual(method.calls, [("client-inputs/abc.png", {"seed": 7})])
        self.assertEqual(call, "fc-direct")

    def test_spawn_rejects_source_inputs_before_any_modal_call(self) -> None:
        with (
            patch.object(router.modal.Cls, "from_name") as lookup,
            self.assertRaises(ValueError),
        ):
            router.spawn_generation("pixal3d", "source-inputs/source.png", {})
        lookup.assert_not_called()


class GenerationJobRunnerTests(unittest.TestCase):
    """`run_generation_job` must validate input and artifact inside the GPU container."""

    def _run(self, *, glb: bytes, options: dict | None = None) -> dict:
        payload = rgba_png()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "client-inputs").mkdir()
            (root / "client-inputs" / "canonical.png").write_bytes(payload)
            (root / "generated").mkdir()
            (root / "generated" / "out.glb").write_bytes(glb)

            def generate_image(image_bytes: bytes, **opts):
                self.assertEqual(image_bytes, payload)
                return {
                    "model": "test-model",
                    "artifact": "generated/out.glb",
                    "glb_bytes": len(glb),
                    "load_s": 1.0,
                    "inference_s": 2.0,
                    "echo": opts,
                }

            class FakeVolume:
                def reload(self):
                    return None

            with patch("modal_3d.common.ARTIFACT_ROOT", str(root)):
                return run_generation_job(
                    "test-model",
                    FakeVolume(),
                    generate_image,
                    "client-inputs/canonical.png",
                    options,
                )

    def test_job_normalizes_the_result_and_records_validation_timings(self) -> None:
        result = self._run(glb=glb_bytes(), options={"seed": 5})
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(result["artifact"]["path"], "generated/out.glb")
        self.assertEqual(result["artifact"]["mime"], "model/gltf-binary")
        self.assertEqual(result["timing"], {"load_s": 1.0, "inference_s": 2.0})
        self.assertEqual(result["metrics"]["echo"], {"seed": 5})
        self.assertIn("job_input_validation_s", result["metrics"]["timings"])
        self.assertIn("job_artifact_validation_s", result["metrics"]["timings"])
        self.assertIn("job_total_s", result["metrics"]["timings"])

    def test_missing_input_is_reported_before_the_model_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:

            class FakeVolume:
                def reload(self):
                    return None

            def generate_image(image_bytes: bytes, **_options):
                raise AssertionError("model must not run without a validated input")

            with (
                patch("modal_3d.common.ARTIFACT_ROOT", temp_dir),
                self.assertRaises(FileNotFoundError),
            ):
                run_generation_job(
                    "test-model",
                    FakeVolume(),
                    generate_image,
                    "client-inputs/absent.png",
                    None,
                )

    def test_artifact_size_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "GLB"):
            self._run(glb=glb_bytes() + b"trailing")


if __name__ == "__main__":
    unittest.main()
