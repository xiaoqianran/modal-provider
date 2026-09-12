from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

FLASHVDM_ENV = "HUNYUAN_ENABLE_FLASHVDM"
COMPILE_ENV = "HUNYUAN_ENABLE_COMPILE"
SAGEATTN_ENV = "USE_SAGEATTN"


def _enabled(env: Mapping[str, str], key: str) -> bool:
    value = str(env.get(key, "0")).strip()
    if value not in {"0", "1"}:
        raise ValueError(f"{key} must be 0 or 1, got {value!r}")
    return value == "1"


@dataclass(frozen=True)
class HunyuanRuntimeAcceleration:
    flashvdm: bool = False
    compile: bool = False
    sageattention: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "HunyuanRuntimeAcceleration":
        values = os.environ if env is None else env
        return cls(
            flashvdm=_enabled(values, FLASHVDM_ENV),
            compile=_enabled(values, COMPILE_ENV),
            sageattention=_enabled(values, SAGEATTN_ENV),
        )

    def as_dict(self) -> dict[str, bool]:
        return {
            "flashvdm": self.flashvdm,
            "torch_compile": self.compile,
            "sageattention": self.sageattention,
        }


def apply_shape_runtime_acceleration(pipe, config: HunyuanRuntimeAcceleration) -> None:
    """Apply load-time shape accelerators with strict capability checks.

    FlashVDM is limited to the decoder on Hunyuan3D-2.1 here: ``replace_vae``
    is deliberately false, so the pinned 2.1 VAE/checkpoint remains unchanged.
    The request's 50-step sampler is also untouched.  ``torch.compile`` is a
    separate A/B switch because its first-call compile cost and dynamic-shape
    behavior must be benchmarked before production adoption.
    """

    if config.flashvdm:
        enable = getattr(pipe, "enable_flashvdm", None)
        if not callable(enable):
            raise RuntimeError("pinned Hunyuan fork does not expose enable_flashvdm")
        enable(replace_vae=False, mc_algo="mc")
    if config.compile:
        compile_pipeline = getattr(pipe, "compile", None)
        if not callable(compile_pipeline):
            raise RuntimeError("pinned Hunyuan fork does not expose compile()")
        compile_pipeline()
