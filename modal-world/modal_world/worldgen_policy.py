from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

NON_REFERENCE_CAMERA_FRAME_BUDGET = 320
TRAJECTORY_GROUPS = ("view", "target", "wonder", "reconstruct")
GARDEN_ALLOWED_SEMANTICS = frozenset({
    "tree",
    "bench",
    "door",
    "gazebo",
    "lamp",
    "pillar",
    "fence",
    "shrub",
})


def camera_frame_count(camera_path: Path) -> int:
    payload = json.loads(camera_path.read_text())
    extrinsic = payload.get("extrinsic", [])
    return len(extrinsic) if isinstance(extrinsic, list) else 0


def trajectory_group(camera_path: Path) -> str:
    name = camera_path.parent.parent.name
    return next((group for group in TRAJECTORY_GROUPS if name.startswith(group)), "other")


def select_camera_files(camera_files: Iterable[Path], frame_budget: int | None) -> list[Path]:
    camera_files = sorted(camera_files)
    if frame_budget is None:
        return camera_files
    if frame_budget <= 0:
        raise ValueError("frame_budget must be positive")

    groups: dict[str, list[Path]] = {group: [] for group in (*TRAJECTORY_GROUPS, "other")}
    for path in camera_files:
        groups[trajectory_group(path)].append(path)

    selected: list[Path] = []
    used_frames = 0
    while any(groups.values()):
        progressed = False
        for group in (*TRAJECTORY_GROUPS, "other"):
            if not groups[group]:
                continue
            candidate = groups[group].pop(0)
            frames = max(camera_frame_count(candidate), 1)
            if selected and used_frames + frames > frame_budget:
                continue
            selected.append(candidate)
            used_frames += frames
            progressed = True
            if used_frames >= frame_budget:
                return sorted(selected)
        if not progressed:
            break
    return sorted(selected)


def sanitize_semantic_labels(
    labels: object,
    allowed: frozenset[str] = GARDEN_ALLOWED_SEMANTICS,
) -> tuple[list[str], list[str]]:
    if not isinstance(labels, list):
        raise ValueError("semantics must be a JSON list")
    normalized = [str(item).strip() for item in labels if str(item).strip()]
    kept = [item for item in normalized if item.lower() in allowed]
    removed = [item for item in normalized if item.lower() not in allowed]
    return kept, removed
