from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from modal_3d import gateway


class FakeTasks:
    def __init__(self, record: dict):
        self.values = {record["task_id"]: record}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def put(self, key, value):
        self.values[key] = value


class FakeCall:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error

    def get(self, timeout):
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
            patch.object(gateway, "tasks", FakeTasks(record)),
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


if __name__ == "__main__":
    unittest.main()
