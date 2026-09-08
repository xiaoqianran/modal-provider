from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SCHEMA_VERSION = 1


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


def fingerprint_files(paths: Iterable[Path], *, root: Path) -> str:
    """Hash names, sizes, and bytes so resume is invalidated when upstream data changes."""
    digest = hashlib.sha256()
    files = sorted((Path(path) for path in paths), key=lambda path: str(path))
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = path
        digest.update(str(relative).encode())
        stat = path.stat()
        digest.update(str(stat.st_size).encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def build_stage_manifest(
    *,
    job_id: str,
    stage: str,
    hyworld_revision: str,
    input_fingerprint: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "job_id": job_id,
        "stage": stage,
        "hyworld_revision": hyworld_revision,
        "input_fingerprint": input_fingerprint,
        "config": config,
    }


def stage_manifest_path(target: Path, stage: str) -> Path:
    return target / ".modal-world" / f"{stage}.json"


def manifest_matches(target: Path, stage: str, expected: dict[str, Any]) -> bool:
    path = stage_manifest_path(target, stage)
    if not path.is_file():
        return False
    try:
        actual = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return actual == expected


def write_stage_manifest(target: Path, stage: str, manifest: dict[str, Any]) -> Path:
    path = stage_manifest_path(target, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path
