# Architecture

The production path is intentionally split into three small layers:

1. `gateway.py` — Modal entrypoints and orchestration only.
2. `gateway_tasks.py` — task persistence, status transitions, and atomic in-flight deduplication.
3. `gateway_routing.py` — request identity, canonical input paths, and worker lookup/spawn.

Workers own model lifecycle, GPU configuration, inference, and artifact generation. Capabilities are the boundary between the gateway and workers; adding a model should normally require a new worker/capability, not a new branch in the gateway.

## Extension rules

- Do not put model-specific routing branches in `gateway.py`; advertise a worker entrypoint in its capability instead.
- Do not mutate `modal-3d-tasks` or `modal-3d-job-keys` outside `TaskCoordinator` and scheduled maintenance through that coordinator.
- Keep Modal worker lookup in `gateway_routing.py`. Task state code must remain usable with plain in-memory fake stores for tests.
- Keep client-facing capabilities free of internal routing metadata.
- Preserve normalized `generation_result` and canonical PNG/GLB validation at worker boundaries.
