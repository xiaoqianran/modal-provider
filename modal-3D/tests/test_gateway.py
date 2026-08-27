from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from modal_3d import gateway, gateway_routing


class FakeDict:
    def __init__(self, values: dict | None = None):
        self.values = dict(values or {})
        self.lock = threading.Lock()

    def get(self, key, default=None):
        with self.lock:
            return self.values.get(key, default)

    def put(self, key, value, *, skip_if_exists: bool = False):
        with self.lock:
            if skip_if_exists and key in self.values:
                return False
            self.values[key] = value
            return True

    def pop(self, key, default=None):
        with self.lock:
            return self.values.pop(key, default)

    def items(self):
        with self.lock:
            return list(self.values.items())


class FakeCall:
    def __init__(self, value=None, error: Exception | None = None, object_id: str = "fc-test"):
        self.value = value
        self.error = error
        self.object_id = object_id

    def get(self, timeout):
        if self.error:
            raise self.error
        return self.value


class FakeSpawnFunction:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def spawn(self, input_path: str, options: dict):
        self.calls.append((input_path, dict(options)))
        return FakeCall(object_id=f"fc-{len(self.calls)}")


class FakeConditionedSpawnFunction:
    def __init__(self):
        self.calls: list[tuple[dict, str, dict]] = []

    def spawn(self, capability: dict, input_path: str, options: dict):
        self.calls.append((dict(capability), input_path, dict(options)))
        return FakeCall(object_id=f"fc-conditioned-{len(self.calls)}")


class FakeRemoteFunction:
    def __init__(self, value):
        self.value = value
        self.calls: list[tuple] = []

    def remote(self, *args):
        self.calls.append(args)
        return self.value


class FakeRemoteMethod:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def spawn(self, input_path: str, options: dict):
        self.calls.append((input_path, dict(options)))
        return FakeCall(object_id=f"fc-direct-{len(self.calls)}")


class FakeRemoteObject:
    def __init__(self, method: FakeRemoteMethod):
        self.generate_job = method


class FakeRemoteClass:
    def __init__(self, method: FakeRemoteMethod):
        self.method = method

    def __call__(self):
        return FakeRemoteObject(self.method)


class FakeHealthFunction:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error

    def remote(self):
        if self.error:
            raise self.error
        return self.value


class GatewayCapabilityTests(unittest.TestCase):
    def test_public_capabilities_strip_internal_generation_entrypoint(self) -> None:
        document = {
            "contract": "modal-3d.capabilities.v2",
            "models": [
                {
                    "id": "test",
                    "generation_entrypoint": {
                        "kind": "class_method",
                        "class_name": "Model",
                        "method_name": "generate_job",
                    },
                }
            ],
        }
        with patch.object(gateway_routing, "capabilities_document", return_value=document):
            public = gateway_routing.public_capabilities(gateway.registry)
        self.assertNotIn("generation_entrypoint", public["models"][0])


class GatewaySubmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = FakeDict()
        self.keys = FakeDict()
        self.spawn = FakeSpawnFunction()
        self.conditioned = FakeConditionedSpawnFunction()
        self.capability = {
            "worker_app": "modal-3d-test",
            "reference": {"warm_seconds": 1, "cold_start_seconds": 90},
        }
        self.patches = [
            patch.object(gateway, "tasks", self.tasks),
            patch.object(gateway, "job_keys", self.keys),
            patch.object(gateway, "model_capability", return_value=self.capability),
            patch.object(
                gateway,
                "validate_options_for_capability",
                side_effect=lambda _cap, opts: dict(opts or {}),
            ),
            patch.object(gateway_routing.modal.Function, "from_name", return_value=self.spawn),
            patch.object(gateway, "conditioned_generation", self.conditioned),
            patch.object(
                gateway.modal.functions.FunctionCall,
                "from_id",
                return_value=FakeCall(error=TimeoutError()),
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_submission_uses_explicit_cold_start_reference(self) -> None:
        record = gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        self.assertEqual(record["cold_start_seconds"], 90)

    def test_submission_does_not_use_warm_latency_as_cold_start(self) -> None:
        self.capability["reference"].pop("cold_start_seconds")
        record = gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        self.assertIsNone(record["cold_start_seconds"])

    def test_direct_generation_entrypoint_spawns_class_method(self) -> None:
        direct = FakeRemoteMethod()
        self.capability["generation_entrypoint"] = {
            "kind": "class_method",
            "class_name": "Model",
            "method_name": "generate_job",
        }
        with patch.object(gateway_routing.modal.Cls, "from_name", return_value=FakeRemoteClass(direct)) as lookup:
            record = gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        lookup.assert_called_once_with("modal-3d-test", "Model")
        self.assertEqual(direct.calls, [("client-inputs/abc.png", {"seed": 42})])
        self.assertEqual(record["task_id"], "fc-direct-1")
        self.assertEqual(self.spawn.calls, [])
        self.assertEqual(self.conditioned.calls, [])

    def test_duplicate_generation_reuses_existing_task(self) -> None:
        first = gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        second = gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        self.assertEqual(len(self.spawn.calls), 1)
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertFalse(first["deduplicated"])
        self.assertTrue(second["deduplicated"])

    def test_concurrent_duplicate_submissions_spawn_once(self) -> None:
        original_spawn = self.spawn.spawn

        def slow_spawn(input_path: str, options: dict):
            time.sleep(0.05)
            return original_spawn(input_path, options)

        self.spawn.spawn = slow_spawn
        with ThreadPoolExecutor(max_workers=8) as executor:
            records = list(
                executor.map(
                    lambda _: gateway._submit("test", "client-inputs/abc.png", {"seed": 42}),
                    range(8),
                )
            )
        self.assertEqual(len(self.spawn.calls), 1)
        self.assertEqual({record["task_id"] for record in records}, {"fc-1"})
        self.assertEqual(sum(bool(record["deduplicated"]) for record in records), 7)

    def test_spawn_failure_releases_atomic_reservation(self) -> None:
        with (
            patch.object(gateway, "spawn_generation", side_effect=RuntimeError("spawn failed")),
            self.assertRaisesRegex(RuntimeError, "spawn failed"),
        ):
            gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        key = gateway_routing.generation_job_key("test", "client-inputs/abc.png", {"seed": 42})
        self.assertIsNone(self.keys.get(key))

    def test_completed_generation_is_not_treated_as_cache(self) -> None:
        first = gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        completed = FakeCall(value={"artifact": {"path": "old.glb"}})
        with patch.object(gateway.modal.functions.FunctionCall, "from_id", return_value=completed):
            second = gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        self.assertEqual(len(self.spawn.calls), 2)
        self.assertNotEqual(first["task_id"], second["task_id"])
        self.assertFalse(second["deduplicated"])

    def test_option_changes_create_distinct_task(self) -> None:
        gateway._submit("test", "client-inputs/abc.png", {"seed": 1})
        gateway._submit("test", "client-inputs/abc.png", {"seed": 2})
        self.assertEqual(len(self.spawn.calls), 2)

    def test_job_key_is_stable_across_option_order(self) -> None:
        left = gateway_routing.generation_job_key("test", "client-inputs/abc.png", {"a": 1, "b": 2})
        right = gateway_routing.generation_job_key("test", "client-inputs/abc.png", {"b": 2, "a": 1})
        self.assertEqual(left, right)

    def test_source_input_uses_conditioned_generation_slice(self) -> None:
        record = gateway._submit("test", "source-inputs/source.jpg", {"seed": 42})
        self.assertEqual(record["task_id"], "fc-conditioned-1")
        self.assertEqual(len(self.conditioned.calls), 1)
        capability, input_path, options = self.conditioned.calls[0]
        self.assertEqual(capability, self.capability)
        self.assertEqual(input_path, "source-inputs/source.jpg")
        self.assertEqual(options, {"seed": 42})
        self.assertEqual(self.spawn.calls, [])

    def test_duplicate_source_input_reuses_existing_conditioned_task(self) -> None:
        first = gateway._submit("test", "source-inputs/source.png", {"seed": 42})
        second = gateway._submit("test", "source-inputs/source.png", {"seed": 42})
        self.assertEqual(len(self.conditioned.calls), 1)
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertTrue(second["deduplicated"])

    def test_only_supported_input_namespaces_are_accepted(self) -> None:
        with self.assertRaisesRegex(ValueError, "client-inputs/ or source-inputs"):
            gateway._submit("test", "sam31/legacy/canonical.png", {})
        self.assertEqual(self.spawn.calls, [])
        self.assertEqual(self.conditioned.calls, [])


class ConditionedGenerationTests(unittest.TestCase):
    def test_conditioning_reuses_worker_routing_and_attaches_evidence(self) -> None:
        conditioner = FakeRemoteFunction(
            {
                "path": "client-inputs/canonical.png",
                "strategy": "birefnet",
                "canonical_sha256": "a" * 64,
            }
        )
        worker_call = FakeCall(
            value={"model": "test", "artifact": {"path": "generated/test.glb"}}
        )
        capability = {"worker_app": "modal-3d-test"}
        with (
            patch.object(gateway.modal.Function, "from_name", return_value=conditioner),
            patch.object(gateway, "spawn_generation", return_value=worker_call) as spawn,
        ):
            value = gateway._condition_and_generate(
                capability, "source-inputs/source.png", {"seed": 42}
            )
        self.assertEqual(conditioner.calls, [("source-inputs/source.png",)])
        spawn.assert_called_once_with(capability, "client-inputs/canonical.png", {"seed": 42})
        self.assertEqual(value["conditioning"]["strategy"], "birefnet")

    def test_invalid_conditioner_result_fails_closed(self) -> None:
        conditioner = FakeRemoteFunction({"strategy": "birefnet"})
        with (
            patch.object(gateway.modal.Function, "from_name", return_value=conditioner),
            self.assertRaisesRegex(TypeError, "conditioner"),
        ):
            gateway._condition_and_generate(
                {"worker_app": "modal-3d-test"}, "source-inputs/source.png", {}
            )


class RegistryReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = FakeDict(
            {"test": {"id": "test", "worker_app": "modal-3d-test"}}
        )
        self.health = FakeDict()

    def test_healthy_worker_resets_failure_counter(self) -> None:
        self.health.put("test", {"consecutive_failures": 2})
        with (
            patch.object(gateway, "registry", self.registry),
            patch.object(gateway, "registry_health", self.health),
            patch.object(
                gateway.modal.Function,
                "from_name",
                return_value=FakeHealthFunction(
                    {"ok": True, "model": "test", "worker_app": "modal-3d-test"}
                ),
            ),
        ):
            result = gateway._reconcile_registry()
        self.assertEqual(result["healthy"], 1)
        self.assertEqual(self.health.get("test")["consecutive_failures"], 0)
        self.assertIn("test", self.registry.values)

    def test_worker_is_removed_only_after_three_consecutive_failures(self) -> None:
        failure = FakeHealthFunction(error=RuntimeError("worker missing"))
        with (
            patch.object(gateway, "registry", self.registry),
            patch.object(gateway, "registry_health", self.health),
            patch.object(gateway.modal.Function, "from_name", return_value=failure),
        ):
            first = gateway._reconcile_registry()
            second = gateway._reconcile_registry()
            third = gateway._reconcile_registry()
        self.assertEqual(first["failures"], {"test": 1})
        self.assertEqual(second["failures"], {"test": 2})
        self.assertEqual(third["removed"], ["test"])
        self.assertNotIn("test", self.registry.values)


if __name__ == "__main__":
    unittest.main()
