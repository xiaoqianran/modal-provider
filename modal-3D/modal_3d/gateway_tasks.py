"""Task persistence and in-flight deduplication for the gateway.

The coordinator is intentionally unaware of Modal worker lookup. It only needs
Dict-like stores and a FunctionCall resolver supplied by the gateway runtime,
which keeps the state machine easy to unit test.
"""

from __future__ import annotations

import time
import uuid


class TaskCoordinator:
    def __init__(
        self,
        tasks,
        job_keys,
        *,
        retention_seconds: float,
        reservation_wait_seconds: float = 5.0,
        reservation_stale_seconds: float = 300.0,
        reservation_poll_seconds: float = 0.02,
    ) -> None:
        self.tasks = tasks
        self.job_keys = job_keys
        self.retention_seconds = retention_seconds
        self.reservation_wait_seconds = reservation_wait_seconds
        self.reservation_stale_seconds = reservation_stale_seconds
        self.reservation_poll_seconds = reservation_poll_seconds

    def create_record(
        self,
        call,
        model: str,
        kind: str,
        capability: dict,
        job_key: str,
    ) -> dict:
        record = {
            "task_id": call.object_id,
            "call_id": call.object_id,
            "job_key": job_key,
            "model": model,
            "kind": kind,
            "status": "running",
            "submitted_at": time.time(),
            "cold_start_seconds": capability.get("reference", {}).get("cold_start_seconds"),
            "deduplicated": False,
        }
        self.tasks.put(call.object_id, record)
        return record

    def _finish(self, task_id: str, record: dict, *, result=None, error: Exception | None = None) -> dict:
        if error is not None:
            record.update(
                {
                    "status": "failed",
                    "finished_at": time.time(),
                    "error": {"type": type(error).__name__, "message": str(error)},
                }
            )
        else:
            record.update({"status": "completed", "finished_at": time.time(), "result": result})
        self.tasks.put(task_id, record)
        return record

    def reusable_task(self, job_key: str, call_from_id) -> dict | None:
        task_id = self.job_keys.get(job_key)
        if not isinstance(task_id, str) or not task_id:
            return None

        record = self.tasks.get(task_id)
        if not record:
            self.job_keys.pop(job_key, None)
            return None
        if time.time() - record.get("submitted_at", 0) > self.retention_seconds:
            self.job_keys.pop(job_key, None)
            return None

        try:
            result = call_from_id(task_id).get(timeout=0)
        except TimeoutError:
            reused = dict(record)
            reused["deduplicated"] = True
            return reused
        except Exception as exc:  # noqa: BLE001 - terminal remote failure permits retry.
            self._finish(task_id, record, error=exc)
            self.job_keys.pop(job_key, None)
            return None

        self._finish(task_id, record, result=result)
        self.job_keys.pop(job_key, None)
        return None

    def reserve(self, job_key: str, call_from_id) -> tuple[dict | None, dict | None]:
        """Atomically reserve a job key or reuse the currently running task."""
        reservation = {
            "state": "reserving",
            "token": uuid.uuid4().hex,
            "reserved_at": time.time(),
        }
        deadline = time.monotonic() + self.reservation_wait_seconds

        while True:
            current = self.job_keys.get(job_key)
            if current is None:
                if self.job_keys.put(job_key, reservation, skip_if_exists=True):
                    return reservation, None
            elif isinstance(current, str):
                reusable = self.reusable_task(job_key, call_from_id)
                if reusable is not None:
                    return None, reusable
            elif isinstance(current, dict) and current.get("state") == "reserving":
                reserved_at = current.get("reserved_at")
                if (
                    isinstance(reserved_at, (int, float))
                    and time.time() - reserved_at > self.reservation_stale_seconds
                ):
                    # Dict has atomic create-if-absent, but no compare-and-delete.
                    # Never clear a reservation in the hot path: an owner may publish
                    # its FunctionCall ID between a separate get() and pop(), which
                    # could otherwise permit a duplicate paid GPU spawn.
                    raise RuntimeError("submission reservation is stale; cleanup is required before retry")
            else:
                raise RuntimeError("job key contains an invalid reservation value")

            if time.monotonic() >= deadline:
                raise RuntimeError("concurrent submission is still being reserved; retry")
            time.sleep(self.reservation_poll_seconds)

    def release(self, job_key: str, reservation: dict) -> None:
        if self.job_keys.get(job_key) == reservation:
            self.job_keys.pop(job_key, None)

    def publish(self, job_key: str, task_id: str) -> None:
        self.job_keys.put(job_key, task_id)

    def status(self, task_id: str, call_from_id) -> dict:
        record = self.tasks.get(task_id)
        if record is None:
            raise KeyError(task_id)
        if record["status"] != "running":
            return record

        try:
            result = call_from_id(task_id).get(timeout=0)
        except TimeoutError:
            elapsed = time.time() - record["submitted_at"]
            cold_start = record.get("cold_start_seconds")
            record["phase"] = (
                "cold_start_or_queued" if cold_start and elapsed < cold_start else "inference"
            )
            return record
        except Exception as exc:  # noqa: BLE001 - the remote exception is the task result.
            return self._finish(task_id, record, error=exc)
        return self._finish(task_id, record, result=result)

    def cleanup(self, cutoff: float) -> int:
        deleted_tasks = 0
        for task_id, record in self.tasks.items():
            if record.get("submitted_at", time.time()) < cutoff:
                self.tasks.pop(task_id, None)
                if record.get("job_key"):
                    self.job_keys.pop(record["job_key"], None)
                deleted_tasks += 1

        for key, task_ref in list(self.job_keys.items()):
            if isinstance(task_ref, str):
                if self.tasks.get(task_ref) is None:
                    self.job_keys.pop(key, None)
            elif isinstance(task_ref, dict):
                reserved_at = task_ref.get("reserved_at")
                if (
                    isinstance(reserved_at, (int, float))
                    and time.time() - reserved_at > self.retention_seconds
                ):
                    # Scheduled cleanup only reclaims abandoned reservations after
                    # the full task-retention window, far beyond a legitimate spawn.
                    self.job_keys.pop(key, None)
            else:
                self.job_keys.pop(key, None)
        return deleted_tasks
