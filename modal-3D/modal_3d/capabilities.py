from __future__ import annotations

from copy import deepcopy

from .common import ModelName

CONTRACT = "modal-3d.capabilities.v1"
PROFILE_RECOMMENDED = "recommended"

_MODEL_CAPABILITIES: dict[ModelName, dict] = {
    ModelName.FASTSAM3D_PP: {
        "id": ModelName.FASTSAM3D_PP.value,
        "name": "FastSAM3D++",
        "description": "最快的几何生成；vertex-color GLB",
        "status": "enabled",
        "worker_app": "modal-3d-fastsam3d",
        "output": "geometry",
        "artifact": {"mime": "model/gltf-binary", "extension": ".glb"},
        "input": {"role": "canonical_rgba", "mime": "image/png", "alpha": "required"},
        "profiles": [
            {
                "id": PROFILE_RECOMMENDED,
                "name": "推荐 · 已验证",
                "options": {"dmd_interval": 1, "dmd_history": 5},
            }
        ],
        "options": {
            "seed": {"type": "integer", "default": 42},
            "dmd_interval": {"type": "integer", "default": 1},
            "dmd_history": {"type": "integer", "default": 5},
        },
        "deployment": {
            "source": "Archerkattri/fastsam3d-plus-plus",
            "source_revision": "36191e491ca0bf9d51cda39aa7b6c91205eb82e3",
            "sam_revision": "2e73555018d2741ccd486e56c24fac41155a1dc6",
        },
        "reference": {"warm_seconds": 6.06},
    },
    ModelName.TRELLIS2_PP: {
        "id": ModelName.TRELLIS2_PP.value,
        "name": "Hermite-TRELLIS2++",
        "description": "1024 cascade 几何；Hermite / DMD",
        "status": "enabled",
        "worker_app": "modal-3d-hermit-trellis2-plus-plus",
        "output": "geometry",
        "artifact": {"mime": "model/gltf-binary", "extension": ".glb"},
        "input": {"role": "canonical_rgba", "mime": "image/png", "alpha": "required"},
        "profiles": [{"id": PROFILE_RECOMMENDED, "name": "推荐 · 已验证", "options": {}}],
        "options": {"seed": {"type": "integer", "default": 42}},
        "deployment": {
            "source": "Archerkattri/hermit-trellis2-plus-plus",
            "source_revision": "2c8402a92ea97c510c09e278fae557771aad774d",
            "build_artifact": "hermit-trellis2-plus-plus-py311-cu124-torch260-sm89-v1",
        },
        "reference": {"warm_seconds": 11.98},
    },
    ModelName.HUNYUAN21_PP: {
        "id": ModelName.HUNYUAN21_PP.value,
        "name": "Hunyuan2.1++",
        "description": "平衡几何；HiCache++ DMD",
        "status": "enabled",
        "worker_app": "modal-3d-hunyuan",
        "output": "geometry",
        "artifact": {"mime": "model/gltf-binary", "extension": ".glb"},
        "input": {"role": "canonical_rgba", "mime": "image/png", "alpha": "required"},
        "profiles": [
            {
                "id": PROFILE_RECOMMENDED,
                "name": "推荐 · 已验证",
                "options": {"interval": 3, "history": 6, "num_inference_steps": 50},
            }
        ],
        "options": {
            "seed": {"type": "integer", "default": 42},
            "interval": {"type": "integer", "default": 3, "minimum": 1},
            "history": {"type": "integer", "default": 6, "minimum": 4},
            "num_inference_steps": {"type": "integer", "default": 50},
        },
        "deployment": {
            "source": "Archerkattri/hunyuan2.1-plus-plus",
            "source_revision": "9efd760fbec8ab490e68b330225ea1fab10de7fd",
            "base_model": "tencent/Hunyuan3D-2.1",
            "base_model_revision": "0b94677654c57bb9a6b6845cd7b704ccf551d327",
        },
        "reference": {"warm_seconds": 29.56},
    },
    ModelName.PIXAL3D: {
        "id": ModelName.PIXAL3D.value,
        "name": "Pixal3D",
        "description": "完整纹理 GLB；1024 cascade + 4096 texture",
        "status": "enabled",
        "worker_app": "modal-3d-pixal3d",
        "output": "textured",
        "artifact": {"mime": "model/gltf-binary", "extension": ".glb"},
        "input": {"role": "canonical_rgba", "mime": "image/png", "alpha": "required"},
        "profiles": [
            {"id": PROFILE_RECOMMENDED, "name": "推荐 · 已验证", "options": {"fov": None}}
        ],
        "options": {
            "seed": {"type": "integer", "default": 42},
            "fov": {"type": "number", "default": None, "nullable": True},
        },
        "deployment": {
            "source": "TencentARC/Pixal3D",
            "source_revision": "cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af",
            "build_artifact": "pixal3d-py310-cu124-torch260-sm89-v1",
        },
        "reference": {"warm_seconds": 108.92},
    },
}

_MODEL_ORDER = (
    ModelName.FASTSAM3D_PP,
    ModelName.TRELLIS2_PP,
    ModelName.HUNYUAN21_PP,
    ModelName.PIXAL3D,
)

_CAPABILITIES = {
    "contract": CONTRACT,
    "generation": {
        "app": "modal-3d-gateway",
        "submit_function": "submit",
        "job_transport": "modal.FunctionCall",
    },
    "models": [_MODEL_CAPABILITIES[model] for model in _MODEL_ORDER],
    "sam": {
        "cloud": {
            "app": "modal-3d-sam31",
            "provider": "cloud",
            "operations": ["segment", "refine", "materialize"],
            "sam3_code_revision": "8f0b7f4d4e7eda2ed606ebde6702c93359ad01da",
            "sam31_revision": "daa63191845a41281374e725f4c9e51c7a824460",
            "canonical": {
                "mime": "image/png",
                "mode": "RGBA",
                "square": True,
                "default_size": 1024,
            },
        }
    },
}


def capabilities_document() -> dict:
    return deepcopy(_CAPABILITIES)


def model_capability(model: str | ModelName) -> dict:
    try:
        model_name = model if isinstance(model, ModelName) else ModelName(model)
    except ValueError as exc:
        raise ValueError(f"unknown model: {model}") from exc
    return _MODEL_CAPABILITIES[model_name]


def worker_app(model: str | ModelName) -> str:
    return str(model_capability(model)["worker_app"])


def profile_options(model: str | ModelName, profile_id: str) -> dict:
    capability = model_capability(model)
    profile = next((item for item in capability["profiles"] if item["id"] == profile_id), None)
    if profile is None:
        raise ValueError(f"model {capability['id']} does not support profile: {profile_id}")
    return dict(profile["options"])


def _validate_value(name: str, value, schema: dict) -> None:
    if value is None:
        if schema.get("nullable"):
            return
        raise ValueError(f"option {name} must not be null")

    expected = schema["type"]
    if expected == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif expected == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        raise RuntimeError(f"unsupported option schema type: {expected}")
    if not valid:
        raise ValueError(f"option {name} must be {expected}")

    minimum = schema.get("minimum")
    if minimum is not None and value < minimum:
        raise ValueError(f"option {name} must be >= {minimum}")
    maximum = schema.get("maximum")
    if maximum is not None and value > maximum:
        raise ValueError(f"option {name} must be <= {maximum}")


def validate_options(model: str | ModelName, options: dict | None) -> dict:
    capability = model_capability(model)
    if options is None:
        return {}
    if not isinstance(options, dict):
        raise TypeError("options must be an object")

    schemas = capability["options"]
    unknown = sorted(set(options) - set(schemas))
    if unknown:
        raise ValueError(f"unknown options for {capability['id']}: {', '.join(unknown)}")

    validated = dict(options)
    for name, value in validated.items():
        _validate_value(name, value, schemas[name])
    return validated
