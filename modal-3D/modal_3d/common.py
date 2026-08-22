from enum import StrEnum

from pydantic import BaseModel, Field


class ModelName(StrEnum):
    HUNYUAN21_PP = "hunyuan2.1-plus-plus"
    SAM3D_PP = "sam3d-plus-plus"
    FASTSAM3D_PP = "fastsam3d-plus-plus"
    TRELLIS2_PP = "hermit-trellis2-plus-plus"


class GenerateRequest(BaseModel):
    model: ModelName
    input_path: str
    options: dict = Field(default_factory=dict)


class GenerateResult(BaseModel):
    model: ModelName
    output_path: str
    elapsed_s: float
