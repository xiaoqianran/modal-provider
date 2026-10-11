import importlib
import os
import sys
import types
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

if not os.environ.get("PROVIDER_TEST_INSTALLED"):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modal_example.artifacts import ArtifactSpec, describe_artifact, validate_artifact
from modal_example.capabilities import list_capabilities
from modal_example.contracts import normalize_request
from modal_example.deployment import deployment_manifest
from modal_example.models import get_model, list_models
from modal_example.models.registry import build_registry


class StandardTests(unittest.TestCase):
    def test_registry(self):
        model = list_models()[0]
        self.assertEqual(get_model(model.id), model)
        with self.assertRaises(KeyError):
            get_model("unknown")
        with self.assertRaises(ValueError):
            build_registry((model, model))
        with self.assertRaises(ValueError):
            build_registry((replace(model, id="BAD_ID"),))
        with self.assertRaises(FrozenInstanceError):
            model.id = "other"

    def test_requests(self):
        request = {"text": " hello "}
        self.assertEqual(normalize_request(request).text, "hello")
        self.assertEqual(request["text"], " hello ")
        for invalid in (
            {},
            {"text": " "},
            {"text": 3},
            {"text": "a" * 1001},
            {"text": "ok", "unknown": True},
            None,
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_request(invalid)

    def test_artifacts(self):
        spec = describe_artifact(b"hello")
        validate_artifact(spec, b"hello")
        with self.assertRaises(ValueError):
            validate_artifact(spec, b"other")
        for changes in (
            {"role": "unknown"},
            {"media_type": "image/png"},
            {"sha256": "bad"},
            {"size_bytes": True},
            {"size_bytes": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(spec, **changes)
        with self.assertRaises(ValueError):
            validate_artifact(replace(spec, size_bytes=9), b"hello")

    def test_metadata_correspondence(self):
        model = list_models()[0]
        self.assertEqual(list_capabilities()[0]["models"], [model.id])
        target = deployment_manifest()["targets"][0]
        self.assertEqual(target["app"], model.worker_app)
        self.assertEqual(target["module"], model.worker_module)
        self.assertEqual(deployment_manifest(), deployment_manifest())

    def test_fake_modal_worker(self):
        calls = []

        class FakeApp:
            def __init__(self, name):
                calls.append(("app", name))

            def cls(self):
                return lambda cls: cls

        fake = types.ModuleType("modal")
        fake.App = FakeApp

        def method():
            def decorate(fn):
                fn.fake_remote = True
                return fn

            return decorate

        fake.method = method
        name = "modal_example.workers.echo"
        sys.modules.pop(name, None)
        try:
            with patch.dict(sys.modules, {"modal": fake}):
                worker = importlib.import_module(name).EchoWorker()
                self.assertTrue(worker.run_job.fake_remote)
                result = worker.run_job({"text": " hello "})
                self.assertEqual(result, worker.echo({"text": "hello"}))
                validate_artifact(ArtifactSpec(**result["artifact"]), result["content"])
                with self.assertRaises(ValueError):
                    worker.run_job({"text": ""})
                self.assertEqual(calls, [("app", get_model("echo-text").worker_app)])
        finally:
            sys.modules.pop(name, None)


if __name__ == "__main__":
    unittest.main()
