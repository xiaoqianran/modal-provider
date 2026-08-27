from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from modal_3d.gateway_tasks import TaskCoordinator


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
    def __init__(self, object_id="fc-1", value=None, error: Exception | None = None):
        self.object_id = object_id
        self.value = value
        self.error = error

    def get(self, timeout):
        if self.error is not None:
            raise self.error
        return self.value


class TaskCoordinatorTests(unittest.TestCase):
    def coordinator(self):
        return TaskCoordinator(
            FakeDict(),
            FakeDict(),
            retention_seconds=60,
            reservation_wait_seconds=1,
            reservation_poll_seconds=0.001,
        )

    def test_record_status_transitions_are_local_to_coordinator(self) -> None:
        coordinator = self.coordinator()
        capability = {"reference": {"cold_start_seconds": 30}}
        coordinator.create_record(FakeCall(), "test", "generation", capability, "job")
        coordinator.publish("job", "fc-1")

        pending = coordinator.status("fc-1", lambda _: FakeCall(error=TimeoutError()))
        self.assertEqual(pending["phase"], "cold_start_or_queued")

        completed = coordinator.status("fc-1", lambda _: FakeCall(value={"ok": True}))
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"], {"ok": True})

    def test_atomic_reservation_has_single_owner(self) -> None:
        coordinator = self.coordinator()
        call = FakeCall(error=TimeoutError())
        capability = {"reference": {"cold_start_seconds": 30}}
        owner_started = threading.Event()

        def submit(index: int):
            reservation, existing = coordinator.reserve("job", lambda _: call)
            if existing is not None:
                return existing["task_id"]
            owner_started.set()
            time.sleep(0.03)
            record = coordinator.create_record(call, "test", "generation", capability, "job")
            coordinator.publish("job", record["task_id"])
            return record["task_id"]

        with ThreadPoolExecutor(max_workers=8) as executor:
            task_ids = list(executor.map(submit, range(8)))
        self.assertTrue(owner_started.is_set())
        self.assertEqual(set(task_ids), {"fc-1"})
        self.assertEqual(len(coordinator.tasks.values), 1)

    def test_release_allows_retry_after_spawn_failure(self) -> None:
        coordinator = self.coordinator()
        reservation, existing = coordinator.reserve("job", lambda _: FakeCall(error=TimeoutError()))
        self.assertIsNone(existing)
        coordinator.release("job", reservation)
        retry, existing = coordinator.reserve("job", lambda _: FakeCall(error=TimeoutError()))
        self.assertIsNotNone(retry)
        self.assertIsNone(existing)

class ReservationSafetyTests(unittest.TestCase):
    def test_stale_reservation_is_not_deleted_in_hot_path(self) -> None:
        tasks = FakeDict()
        keys = FakeDict(
            {
                "job": {
                    "state": "reserving",
                    "token": "owner",
                    "reserved_at": time.time() - 10,
                }
            }
        )
        coordinator = TaskCoordinator(
            tasks,
            keys,
            retention_seconds=60,
            reservation_wait_seconds=0.01,
            reservation_stale_seconds=1,
            reservation_poll_seconds=0.001,
        )
        with self.assertRaisesRegex(RuntimeError, "stale"):
            coordinator.reserve("job", lambda _: FakeCall(error=TimeoutError()))
        self.assertEqual(keys.get("job")["token"], "owner")

    def test_cleanup_does_not_reclaim_recent_stale_reservation(self) -> None:
        tasks = FakeDict()
        reservation = {
            "state": "reserving",
            "token": "owner",
            "reserved_at": time.time() - 10,
        }
        keys = FakeDict({"job": reservation})
        coordinator = TaskCoordinator(
            tasks,
            keys,
            retention_seconds=60,
            reservation_stale_seconds=1,
        )
        coordinator.cleanup(time.time() - 60)
        self.assertEqual(keys.get("job"), reservation)

    def test_cleanup_reclaims_reservation_only_after_retention_window(self) -> None:
        tasks = FakeDict()
        keys = FakeDict(
            {
                "job": {
                    "state": "reserving",
                    "token": "owner",
                    "reserved_at": time.time() - 120,
                }
            }
        )
        coordinator = TaskCoordinator(tasks, keys, retention_seconds=60, reservation_stale_seconds=1)
        coordinator.cleanup(time.time() - 60)
        self.assertIsNone(keys.get("job"))
