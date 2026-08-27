"""Pure planning and validation helpers for paid 3D benchmark runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from modal_3d.common import validate_canonical_png
from modal_3d.png import foreground_stats
from modal_3d.gateway_routing import generation_job_key


@dataclass(frozen=True)
class Scene:
    id: str
    canonical: Path
    modal_path: str
    sha256: str
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
        if isinstance(canonical_value, dict):
            canonical_path = canonical_value.get("path")
            modal_path = canonical_value.get("modal_path")
        else:
            canonical_path = canonical_value
            modal_path = row.get("modal_path")
        if not isinstance(canonical_path, str) or not isinstance(modal_path, str):
            raise ValueError(f"{scene_id}: canonical path and modal_path are required")
        candidate = Path(canonical_path)
        canonical = (
            (path.parent / candidate).resolve()
            if not candidate.parts or candidate.parts[0] != "benchmarks"
            else (path.parents[1] / candidate).resolve()
        )
        if not canonical.is_file():
            raise FileNotFoundError(canonical)
        if not modal_path.startswith("client-inputs/") or ".." in Path(modal_path).parts:
            raise ValueError(f"{scene_id}: modal_path must be under client-inputs/")

        payload = canonical.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if isinstance(canonical_value, dict):
            declared_sha = canonical_value.get("sha256")
            declared_bytes = canonical_value.get("bytes")
            if declared_sha is not None and declared_sha != digest:
                raise ValueError(f"{scene_id}: canonical SHA256 does not match manifest")
            if declared_bytes is not None and declared_bytes != len(payload):
                raise ValueError(f"{scene_id}: canonical byte count does not match manifest")
        if Path(modal_path).stem != digest:
            raise ValueError(f"{scene_id}: modal_path filename must equal canonical SHA256")
        contract = validate_canonical_png(canonical)
        stats = foreground_stats(payload, contract["width"], contract["height"])
        allow_low_information = row.get("allow_low_information", False)
        if not isinstance(allow_low_information, bool):
            raise TypeError(f"{scene_id}: allow_low_information must be boolean")
        if (
            not allow_low_information
            and stats["foreground_rgb_nonzero_fraction"] < min_rgb_nonzero_fraction
        ):
            raise ValueError(
                f"{scene_id}: foreground RGB contains too little information "
                f"({stats['foreground_rgb_nonzero_fraction']:.6f}); "
                "set allow_low_information=true only after manual review"
            )
        scenes.append(
            Scene(
                id=scene_id,
                canonical=canonical,
                modal_path=modal_path,
                sha256=digest,
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
        "scenes": [
            {"id": scene.id, "modal_path": scene.modal_path, "sha256": scene.sha256}
            for scene in scenes
        ],
        "total_calls": calls_per_model * len(model_ids),
        "estimated_gpu_seconds": estimated_gpu_seconds,
        "models": rows,
    }




def recover_task_id(model_id: str, modal_path: str, options: dict, job_keys, tasks, *, intent_at: float) -> str | None:
    """Recover a task spawned before local state persisted its FunctionCall ID.

    The fast path uses the live job-key index. The task scan is only a crash
    recovery fallback and therefore does not add overhead to normal submissions.
    """
    key = generation_job_key(model_id, modal_path, options)
    indexed = job_keys.get(key)
    if isinstance(indexed, str):
        record = tasks.get(indexed)
        if isinstance(record, dict) and record.get("job_key") == key:
            return indexed

    matches: list[tuple[float, str]] = []
    for task_id, record in tasks.items():
        if not isinstance(record, dict) or record.get("job_key") != key:
            continue
        submitted_at = record.get("submitted_at")
        if isinstance(submitted_at, (int, float)) and submitted_at >= intent_at - 1:
            matches.append((float(submitted_at), str(task_id)))
    if not matches:
        return None
    return max(matches)[1]


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
    fields = ("id", "worker_app", "deployment", "options", "reference")
    for field in fields:
        if local.get(field) != deployed.get(field):
            raise ValueError(f"{local['id']}: deployed {field} does not match local code")
    local_profile = recommended_profile(local)
    deployed_profile = recommended_profile(deployed)
    if local_profile != deployed_profile:
        raise ValueError(f"{local['id']}: deployed recommended profile does not match local code")
