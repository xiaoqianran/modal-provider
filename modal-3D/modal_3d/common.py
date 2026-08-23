from enum import Enum


class ModelName(str, Enum):
    HUNYUAN21_PP = "hunyuan2.1-plus-plus"
    FASTSAM3D_PP = "fastsam3d-plus-plus"
    TRELLIS2_PP = "hermit-trellis2-plus-plus"
    PIXAL3D = "pixal3d"


def generation_result(model: ModelName, value: dict) -> dict:
    path = value.get("artifact")
    size = value.get("glb_bytes")
    if not path or size is None:
        raise ValueError("worker result must contain artifact and glb_bytes")

    timing = {key: value[key] for key in ("load_s", "inference_s") if key in value}
    reserved = {"model", "artifact", "glb_bytes", *timing}
    return {
        "model": model.value,
        "artifact": {"path": path, "bytes": size, "mime": "model/gltf-binary"},
        "timing": timing,
        "metrics": {key: val for key, val in value.items() if key not in reserved},
    }
