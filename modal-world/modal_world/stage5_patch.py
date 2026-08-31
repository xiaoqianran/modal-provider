from __future__ import annotations

from pathlib import Path


def patch_stage5_single_gpu(source_root: str | Path) -> None:
    """Guard HYWorld2's final mesh-export barrier on the pinned single-GPU path."""
    script = Path(source_root) / "hyworld2/worldgen/world_gs_trainer.py"
    source = script.read_text(encoding="utf-8")

    barrier_old = "                    dist.barrier()\n"
    barrier_new = "                    if world_size > 1:\n                        dist.barrier()\n"
    if source.count(barrier_old) != 1:
        raise RuntimeError("expected unique pinned Stage 5 mesh-export barrier not found")

    script.write_text(source.replace(barrier_old, barrier_new, 1), encoding="utf-8")
