"""Registry health reconciliation for deployed 3D workers."""

from __future__ import annotations

import time


def reconcile_registry(registry, health_state, health_probe, *, failure_limit: int = 3) -> dict:
    """Probe registered workers and evict only persistently unhealthy entries."""
    checked = 0
    healthy = 0
    removed: list[str] = []
    failures: dict[str, int] = {}

    for model_id, capability in list(registry.items()):
        checked += 1
        worker_app = str(capability.get("worker_app", ""))
        try:
            probe = health_probe(worker_app)
            if (
                not isinstance(probe, dict)
                or probe.get("ok") is not True
                or probe.get("model") != model_id
            ):
                raise RuntimeError("worker health payload does not match registry entry")
        except Exception as exc:  # noqa: BLE001 - health failures are persisted, not surfaced.
            previous = health_state.get(model_id, {}) or {}
            count = int(previous.get("consecutive_failures", 0)) + 1
            failures[model_id] = count
            health_state.put(
                model_id,
                {
                    "consecutive_failures": count,
                    "last_failure_at": time.time(),
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
            )
            if count >= failure_limit:
                registry.pop(model_id, None)
                health_state.pop(model_id, None)
                removed.append(model_id)
        else:
            healthy += 1
            health_state.put(
                model_id,
                {
                    "consecutive_failures": 0,
                    "last_success_at": time.time(),
                },
            )

    return {"checked": checked, "healthy": healthy, "removed": removed, "failures": failures}
