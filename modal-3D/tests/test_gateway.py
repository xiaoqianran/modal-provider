from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from modal_3d import gateway


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
        with patch.object(gateway, "capabilities_document", return_value=document):
            public = gateway._public_capabilities()
        self.assertNotIn("generation_entrypoint", public["models"][0])


class GatewayStatusTests(unittest.TestCase):
    def record(self) -> dict:
        return {
            "task_id": "fc-test",
            "call_id": "fc-test",
            "model": "test",
            "kind": "generation",
            "status": "running",
            "submitted_at": time.time(),
            "cold_start_seconds": 198,
        }

    def status(self, call: FakeCall) -> dict:
        record = self.record()
        with (
            patch.object(gateway, "tasks", FakeDict({record["task_id"]: record})),
            patch.object(gateway.modal.functions.FunctionCall, "from_id", return_value=call),
        ):
            return gateway._status(record["task_id"])

    def test_pending_task_reports_cold_start_phase(self) -> None:
        value = self.status(FakeCall(error=TimeoutError()))
        self.assertEqual(value["status"], "running")
        self.assertEqual(value["phase"], "cold_start_or_queued")

    def test_completed_task_returns_result(self) -> None:
        value = self.status(FakeCall(value={"artifact": "model.glb"}))
        self.assertEqual(value["status"], "completed")
        self.assertEqual(value["result"], {"artifact": "model.glb"})

    def test_failed_task_returns_remote_error(self) -> None:
        value = self.status(FakeCall(error=ValueError("bad input")))
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["error"], {"type": "ValueError", "message": "bad input"})


class GatewaySubmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = FakeDict()
        self.keys = FakeDict()
        self.spawn = FakeSpawnFunction()
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
            patch.object(gateway.modal.Function, "from_name", return_value=self.spawn),
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
        with patch.object(gateway.modal.Cls, "from_name", return_value=FakeRemoteClass(direct)) as lookup:
            record = gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        lookup.assert_called_once_with("modal-3d-test", "Model")
        self.assertEqual(direct.calls, [("client-inputs/abc.png", {"seed": 42})])
        self.assertEqual(record["task_id"], "fc-direct-1")
        self.assertEqual(self.spawn.calls, [])

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
        with patch.object(gateway, "_spawn_generation", side_effect=RuntimeError("spawn failed")):
            with self.assertRaisesRegex(RuntimeError, "spawn failed"):
                gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        key = gateway._job_key("test", "client-inputs/abc.png", {"seed": 42})
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
        left = gateway._job_key("test", "client-inputs/abc.png", {"a": 1, "b": 2})
        right = gateway._job_key("test", "client-inputs/abc.png", {"b": 2, "a": 1})
        self.assertEqual(left, right)

    def test_only_client_inputs_are_accepted(self) -> None:
        with self.assertRaisesRegex(ValueError, "client-inputs"):
            gateway._submit("test", "sam31/legacy/canonical.png", {})
        self.assertEqual(self.spawn.calls, [])


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
