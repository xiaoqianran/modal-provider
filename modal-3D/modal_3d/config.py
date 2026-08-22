from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    repo: str
    gpu: str = "L40S"
    max_containers: int = 1


MODELS = {
    "hunyuan2.1-plus-plus": ModelSpec("Archerkattri/hunyuan2.1-plus-plus"),
    "fastsam3d-plus-plus": ModelSpec("Archerkattri/fastsam3d-plus-plus"),
    "hermit-trellis2-plus-plus": ModelSpec("Archerkattri/hermit-trellis2-plus-plus"),
    "trellis.cpp": ModelSpec("pwilkin/trellis.cpp"),
    "pixal3d": ModelSpec("TencentARC/Pixal3D"),
}
