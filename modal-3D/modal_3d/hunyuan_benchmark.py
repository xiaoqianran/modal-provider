from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from .hunyuan_runtime import COMPILE_ENV, FLASHVDM_ENV, SAGEATTN_ENV

CANONICAL_STATION_INPUT = (
    "client-inputs/975c69fb112a3ea3048d1b56238e4f0ce2528830a328157f8dc5882a04da232d.png"
)
FROZEN_QUALITY_OPTIONS: dict[str, Any] = {
    "seed": 42,
    "acceleration": "base",
    "interval": 1,
    "history": 6,
    "num_inference_steps": 50,
    "paint_remesh": True,
}


@dataclass(frozen=True)
class BenchmarkVariant:
    name: str
    flashvdm: bool = False
    compile: bool = False
    sageattention: bool = False
    ready: bool = True
    requires_artifact: str | None = None

    @property
    def env(self) -> dict[str, str]:
        return {
            FLASHVDM_ENV: "1" if self.flashvdm else "0",
            COMPILE_ENV: "1" if self.compile else "0",
            SAGEATTN_ENV: "1" if self.sageattention else "0",
        }


VARIANTS: dict[str, BenchmarkVariant] = {
    "base-official": BenchmarkVariant(name="base-official"),
    "flashvdm-decoder": BenchmarkVariant(name="flashvdm-decoder", flashvdm=True),
    "compile-official": BenchmarkVariant(name="compile-official", compile=True),
    "flashvdm-compile": BenchmarkVariant(
        name="flashvdm-compile", flashvdm=True, compile=True
    ),
    # SageAttention is quantized attention. Keep it gated until a pinned SM89
    # build artifact and same-seed geometry/PBR quality comparison exist.
    "sageattention": BenchmarkVariant(
        name="sageattention",
        sageattention=True,
        ready=False,
        requires_artifact="hunyuan21-py311-cu124-torch251-sm89-sage-v1",
    ),
}


def get_variant(name: str, *, allow_unreleased: bool = False) -> BenchmarkVariant:
    try:
        variant = VARIANTS[name]
    except KeyError as exc:
        raise ValueError(f"unknown Hunyuan benchmark variant: {name}") from exc
    if not variant.ready and not allow_unreleased:
        raise RuntimeError(
            f"variant {name!r} is gated until artifact {variant.requires_artifact!r} is available"
        )
    return variant


def validate_warmup(variant: BenchmarkVariant, warmup: dict[str, Any]) -> None:
    actual = warmup.get("runtime_acceleration")
    expected = {
        "flashvdm": variant.flashvdm,
        "torch_compile": variant.compile,
        "sageattention": variant.sageattention,
    }
    if actual != expected:
        raise RuntimeError(
            f"Hunyuan runtime acceleration mismatch: expected {expected}, got {actual}"
        )


def _median(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 6) if values else None


def summarize_runs(records: list[dict[str, Any]]) -> dict[str, Any]:
    def collect(path: tuple[str, ...]) -> list[float]:
        values: list[float] = []
        for record in records:
            value: Any = record
            for key in path:
                if not isinstance(value, dict) or key not in value:
                    value = None
                    break
                value = value[key]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
        return values

    return {
        "runs": len(records),
        "client_e2e_median_s": _median(collect(("client_e2e_s",))),
        "inference_median_s": _median(collect(("result", "timing", "inference_s"))),
        "shape_median_s": _median(collect(("result", "metrics", "shape_s"))),
        "paint_median_s": _median(collect(("result", "metrics", "paint_s"))),
        "peak_vram_allocated_max_gb": max(
            collect(("result", "metrics", "peak_vram_allocated_gb")), default=None
        ),
    }
