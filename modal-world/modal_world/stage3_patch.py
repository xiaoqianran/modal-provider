from __future__ import annotations

from pathlib import Path

from .worldstereo_patch import patch_worldstereo_wrapper


def patch_stage3_runtime(source_root: str | Path) -> None:
    """Apply pinned WorldStereo/DINO offline fixes at image build time."""
    root = Path(source_root)
    worldgen_root = root / "hyworld2/worldgen"
    patch_worldstereo_wrapper(worldgen_root / "models/worldstereo_wrapper.py")

    retrieval_path = worldgen_root / "src/retrieval_wm.py"
    source = retrieval_path.read_text()
    processor_old = "            self.processor = AutoImageProcessor.from_pretrained(model_path, use_fast=True)\n"
    processor_new = (
        "            self.processor = AutoImageProcessor.from_pretrained(\n"
        "                model_path, use_fast=True, local_files_only=True\n"
        "            )\n"
    )
    model_old = "            self.model = AutoModel.from_pretrained(model_path).to(self.device)\n"
    model_new = (
        "            self.model = AutoModel.from_pretrained(\n"
        "                model_path, local_files_only=True\n"
        "            ).to(self.device)\n"
    )
    if source.count(processor_old) != 1:
        raise RuntimeError("expected pinned DINO processor loader not found")
    if source.count(model_old) != 1:
        raise RuntimeError("expected pinned DINO model loader not found")
    source = source.replace(processor_old, processor_new, 1)
    source = source.replace(model_old, model_new, 1)

    import_marker = "import subprocess\n"
    if source.count(import_marker) != 1:
        raise RuntimeError("expected pinned retrieval_wm import block not found")
    source = source.replace(import_marker, import_marker + "import time\n", 1)

    alignment_start = "    def alignment(self, debug_mode=False):\n"
    if source.count(alignment_start) != 1:
        raise RuntimeError("expected pinned alignment definition not found")
    source = source.replace(
        alignment_start,
        alignment_start
        + "        self.alignment_profile = {}\n"
        + "        _alignment_phase_started = time.perf_counter()\n",
        1,
    )

    phase_markers = [
        (
            "phase1_mapping",
            "        # Phase 2: Preprocessing -- precompute MoGe depth and SAM3 sky masks by video.\n",
        ),
        (
            "phase2_preprocess_align",
            "        # Phase 3: Synchronize k,b results in video_align_cache across processes.\n",
        ),
        (
            "phase3_sync_kb",
            "        # Phase 4: Detect abnormal k,b values based on anchor depths.\n",
        ),
        (
            "phase4_detect_kb_anomalies",
            "        # Phase 5: Classify each frame on this rank as inlier/outlier and determine the final k,b.\n",
        ),
        (
            "phase5_finalize_kb",
            "        # Phase 6: Generate aligned depth, update_mask, and point clouds with final_k and final_b.\n",
        ),
        (
            "phase6_build_pointclouds",
            "        # Phase 6.5: Filter outlier points after video-level aggregation with Statistical Outlier Removal.\n",
        ),
        (
            "phase6_5_sor",
            "        # Phase 7: Save cameras.json and synchronize point-cloud data across ranks.\n",
        ),
    ]
    for phase_name, marker in phase_markers:
        if source.count(marker) != 1:
            raise RuntimeError(f"expected pinned alignment marker not found: {phase_name}")
        timing = (
            f'        self.alignment_profile["{phase_name}"] = '
            "time.perf_counter() - _alignment_phase_started\n"
            "        _alignment_phase_started = time.perf_counter()\n"
        )
        source = source.replace(marker, timing + marker, 1)

    alignment_pos = source.index(alignment_start)
    next_method = source.find("\n    def ", alignment_pos + len(alignment_start))
    if next_method == -1:
        next_method = len(source)
    alignment_source = source[alignment_pos:next_method]
    final_barrier = alignment_source.rfind("        dist.barrier()\n")
    if final_barrier == -1:
        raise RuntimeError("expected final pinned alignment barrier not found")
    insert_pos = alignment_pos + final_barrier
    final_timing = (
        '        self.alignment_profile["phase7_save_sync"] = '
        "time.perf_counter() - _alignment_phase_started\n"
        '        self.alignment_profile["total"] = sum(self.alignment_profile.values())\n'
    )
    source = source[:insert_pos] + final_timing + source[insert_pos:]

    retrieval_path.write_text(source)
