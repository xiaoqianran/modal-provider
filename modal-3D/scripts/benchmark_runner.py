"""Pure planning and validation helpers for paid 3D benchmark runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from modal_3d.common import validate_canonical_png
from modal_3d.png import foreground_stats


@dataclass(frozen=True)
class Scene:
    id: str
    canonical: Path
    modal_path: str
    prompt: str = ""


def recommended_profile(capability: dict) -> dict:
    profiles = capability.get("profiles") or []
    profile = next((item for item in profiles if item.get("id") == "recommended"), None)
    if not isinstance(profile, dict):
        raise ValueError(f"{capability.get('id', '?')} has no recommended profile")
    return profile


def profile_fingerprint(capability: dict) -> str:
    profile = recommended_profile(capability)
    payload = {
        "model": capability["id"],
        "options": profile["options"],
        "quality": profile.get("quality"),
        "deployment": capability.get("deployment"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_manifest(path: Path, *, min_rgb_nonzero_fraction: float = 0.01) -> list[Scene]:
    data = json.loads(path.read_text())
    rows = data.get("scenes")
    if not isinstance(rows, list) or not rows:
        raise ValueError("benchmark manifest must contain non-empty scenes[]")

    scenes: list[Scene] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("each scene must be an object")
        scene_id = row.get("id")
        if not isinstance(scene_id, str) or not scene_id or scene_id in seen:
            raise ValueError(f"invalid or duplicate scene id: {scene_id!r}")
        seen.add(scene_id)

        canonical_value = row.get("canonical")
        modal_path = row.get("modal_path")
        if not isinstance(canonical_value, str) or not isinstance(modal_path, str):
            raise ValueError(f"{scene_id}: canonical and modal_path are required")
        canonical = (path.parent / canonical_value).resolve()
        if not canonical.is_file():
            raise FileNotFoundError(canonical)
        if not modal_path.startswith("client-inputs/") or ".." in Path(modal_path).parts:
            raise ValueError(f"{scene_id}: modal_path must be under client-inputs/")

        contract = validate_canonical_png(canonical)
        stats = foreground_stats(canonical.read_bytes(), contract["width"], contract["height"])
        if stats["foreground_rgb_nonzero_fraction"] < min_rgb_nonzero_fraction:
            raise ValueError(
                f"{scene_id}: foreground RGB contains too little information "
                f"({stats['foreground_rgb_nonzero_fraction']:.6f})"
            )
        scenes.append(
            Scene(
                id=scene_id,
                canonical=canonical,
                modal_path=modal_path,
                prompt=str(row.get("prompt") or ""),
            )
        )
    return scenes


def build_plan(capabilities: list[dict], scenes: list[Scene], model_ids: list[str], *, full: bool) -> dict:
    by_id = {item["id"]: item for item in capabilities}
    missing = sorted(set(model_ids) - set(by_id))
    if missing:
        raise ValueError(f"unknown models in benchmark plan: {', '.join(missing)}")

    calls_per_model = len(scenes) if full else 1
    rows = []
    estimated_gpu_seconds = 0.0
    for model_id in model_ids:
        capability = by_id[model_id]
        reference = capability.get("reference") or {}
        warm = float(reference.get("warm_seconds") or 0.0)
        cold = float(reference.get("cold_start_seconds") or 0.0)
        estimate = cold + warm * calls_per_model
        estimated_gpu_seconds += estimate
        profile = recommended_profile(capability)
        rows.append(
            {
                "model": model_id,
                "calls": calls_per_model,
                "estimated_gpu_seconds": estimate,
                "profile": profile["options"],
                "quality": profile.get("quality"),
                "reference": reference,
                "fingerprint": profile_fingerprint(capability),
            }
        )
    return {
        "mode": "full" if full else "smoke",
        "scene_count": len(scenes),
        "total_calls": calls_per_model * len(model_ids),
        "estimated_gpu_seconds": estimated_gpu_seconds,
        "models": rows,
    }


def validate_budget(plan: dict, *, max_calls: int, max_estimated_gpu_seconds: float) -> None:
    if plan["total_calls"] > max_calls:
        raise ValueError(
            f"planned calls {plan['total_calls']} exceed --max-calls {max_calls}; "
            "increase the limit explicitly"
        )
    if plan["estimated_gpu_seconds"] > max_estimated_gpu_seconds:
        raise ValueError(
            f"estimated GPU seconds {plan['estimated_gpu_seconds']:.1f} exceed budget "
            f"{max_estimated_gpu_seconds:.1f}; increase the limit explicitly"
        )


def assert_deployed_matches(local: dict, deployed: dict) -> None:
    fields = ("id", "worker_app", "deployment")
    for field in fields:
        if local.get(field) != deployed.get(field):
            raise ValueError(f"{local['id']}: deployed {field} does not match local code")
    local_profile = recommended_profile(local)
    deployed_profile = recommended_profile(deployed)
    if local_profile.get("options") != deployed_profile.get("options"):
        raise ValueError(f"{local['id']}: deployed recommended options do not match local code")
    if local_profile.get("quality") != deployed_profile.get("quality"):
        raise ValueError(f"{local['id']}: deployed quality metadata does not match local code")
