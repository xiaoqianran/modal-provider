"""Final world artifact inventory and integrity checks (no GPU dependencies)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..worldgen_job import runtime_result_dir, stage5_artifacts


def _runtime_world_artifact(path, *, job_id: str, role: str, mime: str, volume_root: Path) -> dict:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"World artifact missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return {
        "id": f"{job_id}_{role.replace('-', '_')}",
        "role": role,
        "mime": mime,
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
        "path": path.relative_to(volume_root).as_posix(),
    }


def collect_world_artifacts(
    target: Path, job_id: str, steps: int, *, volume_root: Path = Path("/worldgen")
) -> list[dict]:
    runtime_dir = runtime_result_dir(target, steps)
    artifacts = [
        _runtime_world_artifact(
            runtime_dir / "environment.ply",
            job_id=job_id,
            volume_root=volume_root,
            role="world-mesh",
            mime="model/ply",
        ),
        _runtime_world_artifact(
            runtime_dir / "semantics.json",
            job_id=job_id,
            volume_root=volume_root,
            role="world-semantics",
            mime="application/json",
        ),
        _runtime_world_artifact(
            stage5_artifacts(target, steps).spz,
            job_id=job_id,
            volume_root=volume_root,
            role="world-visual",
            mime="model/spz",
        ),
        _runtime_world_artifact(
            runtime_dir / "world.json",
            job_id=job_id,
            volume_root=volume_root,
            role="world-manifest",
            mime="application/json",
        ),
    ]
    navigation_path = runtime_dir / "navigation.ply"
    if navigation_path.is_file():
        artifacts.append(
            _runtime_world_artifact(
                navigation_path,
                job_id=job_id,
            volume_root=volume_root,
                role="world-navigation",
                mime="model/ply",
            )
        )
    return artifacts
