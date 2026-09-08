from __future__ import annotations

from pathlib import Path


def _throttle_progress_description(source: str, every: int = 50) -> str:
    """Avoid per-step GPU synchronizations that exist only for tqdm text."""
    lines = source.splitlines(keepends=True)
    starts = [
        i for i, line in enumerate(lines) if line.lstrip().startswith('desc = f"loss=')
    ]
    ends = [i for i, line in enumerate(lines) if line.strip() == "pbar.set_description(desc)"]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise RuntimeError("expected unique pinned Stage 5 tqdm description block not found")

    start, end = starts[0], ends[0]
    indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    guarded = [
        f"{indent}# Progress text is observability-only; do not synchronize GPU every step.\n",
        f"{indent}if step % {int(every)} == 0 or step == max_steps - 1:\n",
    ]
    guarded.extend("    " + line for line in lines[start : end + 1])
    return "".join([*lines[:start], *guarded, *lines[end + 1 :]])


def patch_stage5_single_gpu(source_root: str | Path) -> None:
    """Patch the pinned single-GPU trainer without changing training math."""
    script = Path(source_root) / "hyworld2/worldgen/world_gs_trainer.py"
    source = script.read_text(encoding="utf-8")

    barrier_old = "                    dist.barrier()\n"
    barrier_new = "                    if world_size > 1:\n                        dist.barrier()\n"
    if source.count(barrier_old) != 1:
        raise RuntimeError("expected unique pinned Stage 5 mesh-export barrier not found")
    source = source.replace(barrier_old, barrier_new, 1)
    source = _throttle_progress_description(source, every=50)

    script.write_text(source, encoding="utf-8")
