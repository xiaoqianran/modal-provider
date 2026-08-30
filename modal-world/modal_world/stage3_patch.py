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

    sor_query_old = "    dists, _ = tree.query(points, k=nb_neighbors + 1)\n"
    sor_query_new = "    dists, _ = tree.query(points, k=nb_neighbors + 1, workers=-1)\n"
    if source.count(sor_query_old) != 1:
        raise RuntimeError("expected pinned single-threaded SOR query not found")
    source = source.replace(sor_query_old, sor_query_new, 1)

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

    phase2_marker = (
        "        # Phase 2: Preprocessing -- precompute MoGe depth and SAM3 sky masks by video.\n"
    )
    if source.count(phase2_marker) != 1:
        raise RuntimeError("expected pinned Phase 2 marker not found")
    source = source.replace(
        phase2_marker,
        phase2_marker
        + '        self.alignment_phase2_profile = {"tensor_prep": 0.0, "moge_infer": 0.0, "sam3_sky": 0.0, "frame_align_total": 0.0}\n',
        1,
    )

    tensor_start = "            gen_tensor = []\n"
    tensor_end = "            updated_tar_w2cs = self.ref_w2cs[global_indices]\n"
    if source.count(tensor_start) != 1 or source.count(tensor_end) != 1:
        raise RuntimeError("expected pinned Phase 2 tensor markers not found")
    source = source.replace(
        tensor_start,
        "            _phase2_sub_started = time.perf_counter()\n" + tensor_start,
        1,
    )
    source = source.replace(
        tensor_end,
        '            self.alignment_phase2_profile["tensor_prep"] += time.perf_counter() - _phase2_sub_started\n'
        + tensor_end,
        1,
    )

    moge_start = "            mono_depths = []\n"
    sam3_comment = "            # Use SAM3 to remove the sky mask.\n"
    if source.count(moge_start) != 1 or source.count(sam3_comment) != 1:
        raise RuntimeError("expected pinned MoGe/SAM3 markers not found")
    source = source.replace(
        moge_start,
        "            _phase2_sub_started = time.perf_counter()\n" + moge_start,
        1,
    )
    source = source.replace(
        sam3_comment,
        '            self.alignment_phase2_profile["moge_infer"] += time.perf_counter() - _phase2_sub_started\n'
        + "            _phase2_sub_started = time.perf_counter()\n"
        + sam3_comment,
        1,
    )

    cache_comment = "            # Initialize the cache for the current video.\n"
    if source.count(cache_comment) != 1:
        raise RuntimeError("expected pinned Phase 2 cache marker not found")
    source = source.replace(
        cache_comment,
        '            self.alignment_phase2_profile["sam3_sky"] += time.perf_counter() - _phase2_sub_started\n'
        + cache_comment,
        1,
    )

    frame_loop = "            for local_i in range(N_align):\n"
    frame_done = "            n_success = sum(1 for f in video_align_cache[video_name]['frames'].values() if f['k'] is not None)\n"
    if source.count(frame_loop) != 1 or source.count(frame_done) != 1:
        raise RuntimeError("expected pinned Phase 2 frame-loop markers not found")
    source = source.replace(
        frame_loop,
        "            _phase2_frames_started = time.perf_counter()\n" + frame_loop,
        1,
    )
    source = source.replace(
        frame_done,
        '            self.alignment_phase2_profile["frame_align_total"] += time.perf_counter() - _phase2_frames_started\n'
        + frame_done,
        1,
    )

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
