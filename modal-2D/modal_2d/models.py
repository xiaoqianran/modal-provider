from __future__ import annotations

from dataclasses import asdict, dataclass

from .constants import IMAGE_SIZE, MAX_BATCH_SIZE


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


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="sana-sprint-0.6b",
        name="SANA-Sprint 0.6B",
        hf_id="Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers",
        revision="aa76e7f4f4928f378716b6716a2130fba3caf5b1",
        parameters="0.6B",
        runtime="sana-sprint",
        worker_app="modal-2d-sana-sprint",
        steps=2,
        guidance=4.5,
        gpu="L40S",
        snapshot_file="model_index.json",
    ),
    ModelSpec(
        id="sana-sprint-1.6b",
        name="SANA-Sprint 1.6B",
        hf_id="Efficient-Large-Model/Sana_Sprint_1.6B_1024px_diffusers",
        revision="19683c58b7ea290e55cedd8950ae1d86ada7ef96",
        parameters="1.6B",
        runtime="sana-sprint",
        worker_app="modal-2d-sana-sprint",
        steps=2,
        guidance=4.5,
        gpu="L40S",
        snapshot_file="model_index.json",
    ),
    ModelSpec(
        id="qwen-image-2512",
        name="Qwen-Image-2512",
        hf_id="Qwen/Qwen-Image-2512",
        revision="25468b98e3276ca6700de15c6628e51b7de54a26",
        parameters="20B",
        runtime="qwen-image",
        worker_app="modal-2d-qwen-image-2512",
        steps=50,
        guidance=4.0,
        gpu="RTX-PRO-6000",
        snapshot_file="model_index.json",
    ),
    ModelSpec(
        id="z-image-turbo",
        name="Z-Image-Turbo",
        hf_id="Tongyi-MAI/Z-Image-Turbo",
        revision="f332072aa78be7aecdf3ee76d5c247082da564a6",
        parameters="6B",
        runtime="z-image",
        worker_app="modal-2d-z-image-turbo",
        steps=9,
        guidance=0.0,
        gpu="L40S",
        snapshot_file="model_index.json",
        guidance_editable=False,
    ),
    ModelSpec(
        id="hidream-o1-image",
        name="HiDream-O1-Image",
        hf_id="HiDream-ai/HiDream-O1-Image",
        revision="0b0901d99f200389e138c61946af1185f5f49a13",
        parameters="8B",
        runtime="hidream-o1",
        worker_app="modal-2d-hidream-o1",
        steps=50,
        guidance=5.0,
        gpu="RTX-PRO-6000",
        snapshot_file="config.json",
    ),
)
DEFAULT_MODEL = "sana-sprint-1.6b"
_MODEL_MAP = {model.id: model for model in MODELS}


def model_spec(model_id: str) -> ModelSpec:
    try:
        return _MODEL_MAP[model_id]
    except KeyError as exc:
        raise ValueError(f"unsupported model: {model_id}") from exc


def model_ids() -> tuple[str, ...]:
    return tuple(model.id for model in MODELS)
