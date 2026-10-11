from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .pipelines.checkpoints import (  # noqa: F401 - compatibility re-exports
    build_stage_manifest,
    fingerprint_files,
    manifest_matches,
    stage_manifest_path,
    write_stage_manifest,
)

_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class Stage5Artifacts:
    ply: Path
    spz: Path
    mesh: Path


def _validated_steps(steps: int) -> int:
    steps = int(steps)
    if steps <= 0:
        raise ValueError("steps must be > 0")
    return steps


def stage5_result_dir(target: Path, steps: int) -> Path:
    """Keep the canonical 8000-step layout while isolating experimental profiles."""
    steps = _validated_steps(steps)
    return target / ("gs_result" if steps == 8000 else f"gs_result_steps_{steps}")


def runtime_result_dir(target: Path, steps: int) -> Path:
    """Keep the canonical final runtime while isolating non-final step profiles."""
    steps = _validated_steps(steps)
    return target / ("runtime" if steps == 8000 else f"runtime_steps_{steps}")


def stage_profile_name(stage: str, steps: int) -> str:
    """Use legacy manifest names for 8000 steps and isolate all other profiles."""
    steps = _validated_steps(steps)
    return stage if steps == 8000 else f"{stage}-steps-{steps}"


def stage_profile_file(target: Path, stem: str, steps: int, suffix: str) -> Path:
    """Resolve profile-specific logs/timing without overwriting the canonical run."""
    steps = _validated_steps(steps)
    name = f"{stem}{suffix}" if steps == 8000 else f"{stem}_steps_{steps}{suffix}"
    return target / name


def stage5_artifacts(target: Path, steps: int) -> Stage5Artifacts:
    """Resolve the trainer's terminal artifacts for an isolated step budget."""
    steps = _validated_steps(steps)
    final_step = steps - 1
    root = stage5_result_dir(target, steps) / "ply"
    return Stage5Artifacts(
        ply=root / f"point_cloud_{final_step}.ply",
        spz=root / f"point_cloud_{final_step}.spz",
        mesh=root / "fuse_post.ply",
    )


def resolve_worldgen_job_root(job_id: str) -> Path:
    """Return an isolated Volume path while preserving the verified legacy case000 path."""
    if not _JOB_ID_RE.fullmatch(job_id):
        raise ValueError(f"invalid worldgen job_id: {job_id!r}")
    if job_id == "case000":
        return Path("/worldgen/case000")
    return Path("/worldgen/jobs") / job_id


