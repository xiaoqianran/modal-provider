from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from modal_3d import gateway


class FakeDict:
    def __init__(self, values: dict | None = None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def put(self, key, value):
        self.values[key] = value

    def pop(self, key, default=None):
        return self.values.pop(key, default)

    def items(self):
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


class FakeHealthFunction:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error

    def remote(self):
        if self.error:
            raise self.error
        return self.value


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
        self.capability = {"worker_app": "modal-3d-test", "reference": {"warm_seconds": 1}}
        self.patches = [
            patch.object(gateway, "tasks", self.tasks),
            patch.object(gateway, "job_keys", self.keys),
            patch.object(gateway, "model_capability", return_value=self.capability),
            patch.object(gateway, "validate_options", side_effect=lambda _m, opts, _r: dict(opts or {})),
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

    def test_duplicate_generation_reuses_existing_task(self) -> None:
        first = gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        second = gateway._submit("test", "client-inputs/abc.png", {"seed": 42})
        self.assertEqual(len(self.spawn.calls), 1)
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertFalse(first["deduplicated"])
        self.assertTrue(second["deduplicated"])

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
