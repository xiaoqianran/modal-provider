from __future__ import annotations

from dataclasses import asdict, dataclass

from ..constants import IMAGE_SIZE, MAX_BATCH_SIZE


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    name: str
    hf_id: str
    revision: str
    parameters: str
    runtime: str
    worker_app: str
    steps: int
    guidance: float
    gpu: str
    snapshot_file: str
    width: int = IMAGE_SIZE
    height: int = IMAGE_SIZE
    worker_class: str = "Model"
    generate_method: str = "generate"
    batch_generate_method: str = "generate_batch"
    batch_max_size: int = MAX_BATCH_SIZE
    guidance_editable: bool = True

    def public(self) -> dict[str, object]:
        value = asdict(self)
        for key in (
            "runtime",
            "gpu",
            "snapshot_file",
            "worker_class",
            "generate_method",
            "batch_generate_method",
            "guidance_editable",
        ):
            value.pop(key, None)
        value["profiles"] = [{"id": "recommended", "steps": self.steps, "guidance": self.guidance}]
        value["generation_entrypoint"] = {
            "app": self.worker_app,
            "class_name": self.worker_class,
            "generate_method": self.generate_method,
            "batch_generate_method": self.batch_generate_method,
        }
        return value



