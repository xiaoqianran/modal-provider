"""Pure CPU checkpoint reuse policy shared by WorldGen stages."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .checkpoints import manifest_matches, stage_manifest_path


@dataclass(frozen=True, slots=True)
class ResumeDecision:
    reuse: bool
    adopt_legacy: bool = False


def decide_resume(
    target: Path, stage: str, manifest: dict[str, Any], *,
    job_id: str, allow_legacy: bool = True,
) -> ResumeDecision:
    """Only case000 may adopt a missing manifest; a mismatch never gets adopted."""
    if manifest_matches(target, stage, manifest):
        return ResumeDecision(reuse=True)
    if allow_legacy and job_id == "case000" and not stage_manifest_path(target, stage).exists():
        return ResumeDecision(reuse=True, adopt_legacy=True)
    return ResumeDecision(reuse=False)
