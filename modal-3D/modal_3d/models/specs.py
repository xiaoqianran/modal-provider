from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Legacy model resource fields plus the canonical generation entrypoint."""

    repo: str
    gpu: str = "L40S"
    max_containers: int = 1
    worker_app: str = ""
    worker_class: str = "Model"
    remote_method: str = "generate_job"
