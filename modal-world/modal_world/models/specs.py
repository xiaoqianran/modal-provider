"""Static World model metadata, independent of GPU backends and Modal imports."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    backend: str
    operations: tuple[str, ...]
    deployment_apps: tuple[str, ...]
