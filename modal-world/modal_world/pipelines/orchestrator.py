"""Sequential WorldGen orchestration with injectable execution boundaries.

Does not import Modal or any GPU runtime; tests use local fake workers.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PipelineDependencies:
    ensure_static_cache: Callable[..., Any]
    worldnav_factory: Callable[..., Any]
    stage0: Callable[..., Any]
    spawn_worker: Callable[..., Any]
    reload_volume: Callable[..., Any]
    resolve_target: Callable[..., Any]
    sanitize_semantics: Callable[..., Any]
    commit_volume: Callable[..., Any]
    worldstereo_factory: Callable[..., Any]
    stage45_factory: Callable[..., Any]
    stage4: Callable[..., Any]
    stage5: Callable[..., Any]
    runtime_compile: Callable[..., Any]


def run_stages(
    *, job_id: str, prompt: str, source_name: str, seed: int, force: bool,
    merge_stage45: bool, steps: int, deps: PipelineDependencies,
) -> dict[str, Any]:
    """Run in original order; return stage results without assembling artifacts."""
    stages = {}
    # Bootstrap cheap static Stage 5 assets before spending on any GPU stage.
    stages["stage5_static_cache"] = deps.ensure_static_cache()
    worldnav_worker = deps.worldnav_factory()
    stages["stage0"] = deps.stage0(
        job_id=job_id,
        source_name=source_name,
        seed=int(seed),
        prompt=prompt,
        force=bool(force),
    )
    stages["stage1"] = deps.spawn_worker(
        worldnav_worker.generate_nav,
        job_id=job_id,
        force=bool(force),
        wait_timeout_s=30 * 60,
    )

    deps.reload_volume()
    target = deps.resolve_target(job_id)
    if job_id != "case000":
        stages["semantic_sanitize"] = deps.sanitize_semantics(target)
        deps.commit_volume()

    stages["stage2"] = deps.spawn_worker(
        worldnav_worker.render,
        job_id=job_id,
        force=bool(force),
        wait_timeout_s=30 * 60,
    )
    stages["stage3"] = deps.spawn_worker(
        deps.worldstereo_factory().generate,
        job_id=job_id,
        force=bool(force),
        wait_timeout_s=45 * 60,
    )
    if merge_stage45:
        stages["stage45"] = deps.stage45_factory().remote(
            job_id=job_id,
            force=bool(force),
            steps=steps,
        )
    else:
        stages["stage4"] = deps.stage4(
            job_id=job_id, force=bool(force)
        )
        stages["stage5"] = deps.stage5(
            job_id=job_id,
            force=bool(force),
            steps=steps,
        )

    runtime_compile = deps.runtime_compile(job_id=job_id, force=bool(force), steps=steps)
    stages["runtime_compile"] = runtime_compile

    return stages
