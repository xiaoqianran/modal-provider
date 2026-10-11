from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    name: str
    runtime: str
    worker_app: str
    gpu: str | None
    operations: tuple[str, ...]
    worker_module: str
    worker_class: str
    business_method: str
    remote_method: str
    hf_id: str | None = None
    revision: str | None = None
