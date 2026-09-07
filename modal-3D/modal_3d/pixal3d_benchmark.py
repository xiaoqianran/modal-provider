from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from .pixal3d_patch import STAGE_CACHE_ENV

CANONICAL_STATION_INPUT = (
    "client-inputs/975c69fb112a3ea3048d1b56238e4f0ce2528830a328157f8dc5882a04da232d.png"
)
FROZEN_QUALITY_OPTIONS: dict[str, Any] = {
    "seed": 42,
    "fov": None,
    "pipeline_type": "1536_cascade",
    "max_num_tokens": 49152,
    "texture_size": 4096,
}


@dataclass(frozen=True)
class BenchmarkVariant:
    name: str
    attention_backend: str
    suppress_stage_empty_cache: bool
    ready: bool = True
    requires_artifact: str | None = None

    @property
    def env(self) -> dict[str, str]:
        return {
            "ATTN_BACKEND": self.attention_backend,
            STAGE_CACHE_ENV: "1" if self.suppress_stage_empty_cache else "0",
            "PIXAL3D_PROFILE": "1",
        }


VARIANTS: dict[str, BenchmarkVariant] = {
    "sdpa-official": BenchmarkVariant(
        name="sdpa-official",
        attention_backend="sdpa",
        suppress_stage_empty_cache=False,
    ),
    "sdpa-no-stage-empty-cache": BenchmarkVariant(
        name="sdpa-no-stage-empty-cache",
        attention_backend="sdpa",
        suppress_stage_empty_cache=True,
    ),
    # Kept fail-closed until the derived FA2 bundle is actually published and
    # wired into the deployed image. The launcher refuses this variant by
    # default so an expensive GPU invocation cannot discover a missing module.
    "fa2-official": BenchmarkVariant(
        name="fa2-official",
        attention_backend="flash_attn",
        suppress_stage_empty_cache=False,
        ready=False,
        requires_artifact="pixal3d-py310-cu124-torch260-sm89-fa2-v1",
    ),
}


def get_variant(name: str, *, allow_unreleased: bool = False) -> BenchmarkVariant:
    try:
        variant = VARIANTS[name]
    except KeyError as exc:
        raise ValueError(f"unknown Pixal3D benchmark variant: {name}") from exc
    if not variant.ready and not allow_unreleased:
        raise RuntimeError(
            f"variant {name!r} is gated until artifact {variant.requires_artifact!r} "
            "is published and wired into the worker image"
        )
    return variant


def validate_warmup(variant: BenchmarkVariant, warmup: dict[str, Any]) -> None:
    if warmup.get("attention_backend") != variant.attention_backend:
        raise RuntimeError(
            "benchmark backend mismatch: expected "
            f"{variant.attention_backend!r}, got {warmup.get('attention_backend')!r}"
        )
    expected_suppressed = variant.suppress_stage_empty_cache
    if bool(warmup.get("stage_empty_cache_suppressed")) != expected_suppressed:
        raise RuntimeError(
            "benchmark allocator-gate mismatch: expected stage_empty_cache_suppressed="
            f"{expected_suppressed}, got {warmup.get('stage_empty_cache_suppressed')!r}"
        )


def _median(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 6) if values else None


def summarize_runs(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize launcher records without discarding per-stage telemetry."""

    def collect(path: tuple[str, ...]) -> list[float]:
        values: list[float] = []
        for record in records:
            value: Any = record
            for key in path:
                if not isinstance(value, dict) or key not in value:
                    value = None
                    break
                value = value[key]
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    return {
        "runs": len(records),
        "client_e2e_median_s": _median(collect(("client_e2e_s",))),
        "worker_total_median_s": _median(
            collect(("result", "metrics", "timings", "worker_total_s"))
        ),
        "inference_median_s": _median(collect(("result", "timing", "inference_s"))),
        "pipeline_median_s": _median(
            collect(("result", "metrics", "timings", "pipeline_s"))
        ),
        "glb_postprocess_median_s": _median(
            collect(("result", "metrics", "timings", "glb_postprocess_s"))
        ),
        "glb_export_median_s": _median(
            collect(("result", "metrics", "timings", "glb_export_s"))
        ),
        "peak_vram_max_gb": max(
            collect(("result", "metrics", "peak_vram_gb")), default=None
        ),
    }
