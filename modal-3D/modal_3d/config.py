from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    repo: str
    gpu: str
    volume: str
    timeout_s: int


MODELS = {
    "hunyuan2.1-plus-plus": ModelSpec(
        repo="Archerkattri/hunyuan2.1-plus-plus", gpu="L40S", volume="modal-3d-hunyuan", timeout_s=1800
    ),
    "sam3d-plus-plus": ModelSpec(
        repo="Archerkattri/sam3d-plus-plus", gpu="L40S", volume="modal-3d-sam3d", timeout_s=1800
    ),
    "fastsam3d-plus-plus": ModelSpec(
        repo="Archerkattri/fastsam3d-plus-plus", gpu="L40S", volume="modal-3d-fastsam3d", timeout_s=1800
    ),
    "hermit-trellis2-plus-plus": ModelSpec(
        repo="Archerkattri/hermit-trellis2-plus-plus", gpu="L40S", volume="modal-3d-trellis2", timeout_s=1800
    ),
}
