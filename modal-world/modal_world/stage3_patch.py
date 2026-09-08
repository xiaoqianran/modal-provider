from __future__ import annotations

from pathlib import Path

from .worldstereo_patch import patch_worldstereo_wrapper


def patch_stage3_runtime(source_root: str | Path) -> None:
    """Apply pinned WorldStereo/DINO offline fixes at image build time."""
    root = Path(source_root)
    worldgen_root = root / "hyworld2/worldgen"
    patch_worldstereo_wrapper(worldgen_root / "models/worldstereo_wrapper.py")

    retrieval_path = worldgen_root / "src/retrieval_wm.py"
    source = retrieval_path.read_text(encoding="utf-8")
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

    percentile_helper_marker = "def calculate_camera_distance(cam1_extrinsic, cam2_extrinsic):\n"
    if source.count(percentile_helper_marker) != 1:
        raise RuntimeError("expected pinned percentile helper insertion marker not found")
    percentile_helper = (
        "def compute_depth_percentile_map_torch(depth, depth_mask):\n"
        "    percentile_map = torch.zeros_like(depth, dtype=torch.float32)\n"
        "    valid_depths = depth[depth_mask]\n"
        "    if valid_depths.numel() == 0:\n"
        "        return percentile_map\n"
        "    sorted_depths = torch.sort(valid_depths).values\n"
        "    ranks = torch.searchsorted(sorted_depths, valid_depths, right=True)\n"
        "    percentile_map[depth_mask] = ranks.to(torch.float32) * (100.0 / valid_depths.numel())\n"
        "    return percentile_map\n\n\n"
    )
    source = source.replace(
        percentile_helper_marker, percentile_helper + percentile_helper_marker, 1
    )

    phase2_marker = (
        "        # Phase 2: Preprocessing -- precompute MoGe depth and SAM3 sky masks by video.\n"
    )
    if source.count(phase2_marker) != 1:
        raise RuntimeError("expected pinned Phase 2 marker not found")
    source = source.replace(
        phase2_marker,
        phase2_marker
        + '        self.alignment_phase2_profile = {"tensor_prep": 0.0, "moge_infer": 0.0, "sam3_sky": 0.0, "frame_align_total": 0.0}\n'
        + '        self.alignment_phase2_detail = {"frame_prep": 0.0, "guided_depth": 0.0, "percentile": 0.0, "normal_mask": 0.0, "ransac": 0.0}\n',
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

    # Phase 2 frame-alignment detail profiling. This is instrumentation only;
    # it must not change any HY-World alignment inputs, thresholds, or outputs.
    frame_prep_start = '                mono_depth_mask = mono_depths[local_i]["mask"][0]\n'
    frame_prep_end = "                # == Global PCD Rendering (obtaining guided_depth) ==\n"
    if source.count(frame_prep_start) != 1 or source.count(frame_prep_end) != 1:
        raise RuntimeError("expected pinned frame-prep markers not found")
    source = source.replace(
        frame_prep_start,
        "                _phase2_detail_started = time.perf_counter()\n" + frame_prep_start,
        1,
    )
    source = source.replace(
        frame_prep_end,
        '                self.alignment_phase2_detail["frame_prep"] += time.perf_counter() - _phase2_detail_started\n'
        + frame_prep_end,
        1,
    )

    guided_call = "                    guided_depth, guided_depth_mask, guided_normal = get_guided_depth_infos_v2(w2c=updated_tar_w2cs[local_i], K=updated_tar_Ks[local_i],\n"
    guided_after = "                    guided_depth_np = guided_depth.cpu().numpy()\n"
    if source.count(guided_call) != 1 or source.count(guided_after) != 1:
        raise RuntimeError("expected pinned guided-depth markers not found")
    source = source.replace(
        guided_call,
        "                    _phase2_detail_started = time.perf_counter()\n" + guided_call,
        1,
    )
    source = source.replace(
        guided_after,
        '                    self.alignment_phase2_detail["guided_depth"] += time.perf_counter() - _phase2_detail_started\n'
        + "                    _phase2_detail_started = time.perf_counter()\n"
        + guided_after,
        1,
    )

    percentile_end = (
        "                    guided_depth_mask = guided_depth_mask & ~percentile_mask\n"
    )
    if source.count(percentile_end) != 1:
        raise RuntimeError("expected pinned percentile marker not found")
    source = source.replace(
        percentile_end,
        percentile_end
        + '                    self.alignment_phase2_detail["percentile"] += time.perf_counter() - _phase2_detail_started\n',
        1,
    )

    normal_start = "                # normal update mask; depth alignment avoids samples with normal angles greater than 90 degrees.\n"
    normal_end = "                valid_mask = guided_depth_mask & mono_depth_mask & mono_edge_mask & normal_mask\n"
    if source.count(normal_start) != 1 or source.count(normal_end) != 1:
        raise RuntimeError("expected pinned normal-mask markers not found")
    source = source.replace(
        normal_start,
        "                _phase2_detail_started = time.perf_counter()\n" + normal_start,
        1,
    )
    source = source.replace(
        normal_end,
        normal_end
        + '                self.alignment_phase2_detail["normal_mask"] += time.perf_counter() - _phase2_detail_started\n',
        1,
    )

    ransac_start = "                # Initialize with least squares.\n                ransac = RANSACRegressor(\n"
    ransac_except = '                except:\n                    color_print(f"[Rank{self.rank}] RANSAC failed for {view_id}/{traj_id}/{fname}, continue...", "error")\n'
    ransac_success = "                b = ransac.estimator_.model.intercept_[0]\n"
    if any(source.count(marker) != 1 for marker in (ransac_start, ransac_except, ransac_success)):
        raise RuntimeError("expected pinned RANSAC markers not found")
    source = source.replace(
        ransac_start,
        "                _phase2_detail_started = time.perf_counter()\n" + ransac_start,
        1,
    )
    source = source.replace(
        ransac_except,
        "                except:\n"
        + '                    self.alignment_phase2_detail["ransac"] += time.perf_counter() - _phase2_detail_started\n'
        + '                    color_print(f"[Rank{self.rank}] RANSAC failed for {view_id}/{traj_id}/{fname}, continue...", "error")\n',
        1,
    )
    source = source.replace(
        ransac_success,
        ransac_success
        + '                self.alignment_phase2_detail["ransac"] += time.perf_counter() - _phase2_detail_started\n',
        1,
    )

    percentile_compute_old = (
        "                    guided_depth_np = guided_depth.cpu().numpy()\n"
        "                    # Compute percentile maps for guided depth and mono depth.\n"
        "                    guided_mono_mask = (guided_depth_mask & mono_depth_mask).cpu().numpy()\n"
        "                    mono_depth_np = mono_depth.cpu().numpy()\n"
        "                    guided_depth_percentile = compute_depth_percentile_map(guided_depth_np, guided_mono_mask)\n"
        "                    mono_depth_percentile = compute_depth_percentile_map(mono_depth_np, guided_mono_mask)\n"
        "                    percentile_mask = np.abs(guided_depth_percentile - mono_depth_percentile) > self.percentile_threshold\n"
        "                    percentile_mask = torch.from_numpy(percentile_mask).bool().to(self.device)\n"
    )
    percentile_compute_new = (
        "                    # Keep percentile ranking on GPU for the normal production path.\n"
        "                    guided_mono_mask = guided_depth_mask & mono_depth_mask\n"
        "                    guided_depth_percentile_t = compute_depth_percentile_map_torch(\n"
        "                        guided_depth, guided_mono_mask\n"
        "                    )\n"
        "                    mono_depth_percentile_t = compute_depth_percentile_map_torch(\n"
        "                        mono_depth, guided_mono_mask\n"
        "                    )\n"
        "                    percentile_mask = (\n"
        "                        torch.abs(guided_depth_percentile_t - mono_depth_percentile_t)\n"
        "                        > self.percentile_threshold\n"
        "                    )\n"
    )
    if source.count(percentile_compute_old) != 1:
        raise RuntimeError("expected pinned CPU percentile compute block not found")
    source = source.replace(percentile_compute_old, percentile_compute_new, 1)

    debug_marker = (
        "                    if debug_mode:\n                        # Visualize debug outputs.\n"
    )
    debug_replacement = (
        "                    if debug_mode:\n"
        "                        guided_depth_np = guided_depth.cpu().numpy()\n"
        "                        mono_depth_np = mono_depth.cpu().numpy()\n"
        "                        guided_depth_percentile = guided_depth_percentile_t.cpu().numpy()\n"
        "                        mono_depth_percentile = mono_depth_percentile_t.cpu().numpy()\n"
        "                        # Visualize debug outputs.\n"
    )
    if source.count(debug_marker) != 1:
        raise RuntimeError("expected pinned percentile debug marker not found")
    source = source.replace(debug_marker, debug_replacement, 1)

    percentile_log_old = '                                    f" depth percentile error ratio: {percentile_mask.float().sum() / (guided_mono_mask.sum() + 1e-7):.5f}", "info")\n'
    percentile_log_new = '                                    f" depth percentile error ratio: {percentile_mask.float().sum() / (guided_mono_mask.float().sum() + 1e-7):.5f}", "info")\n'
    if source.count(percentile_log_old) != 1:
        raise RuntimeError("expected pinned percentile log line not found")
    source = source.replace(percentile_log_old, percentile_log_new, 1)

    # Phase 6 builds large per-video point clouds. Upstream repeatedly
    # np.concatenate()s the full accumulated array for every frame, producing
    # quadratic memory copies. Preserve chunk order and concatenate exactly once.
    aggregate_init_old = (
        '            video_aligned_data[video_name] = {"points": None, "colors": None}\n'
    )
    aggregate_init_new = (
        "            video_aligned_data[video_name] = {\n"
        '                "points": None, "colors": None, "point_chunks": [], "color_chunks": []\n'
        "            }\n"
    )
    aggregate_old = (
        "                # Aggregate at video level.\n"
        '                if video_aligned_data[video_name]["points"] is None:\n'
        '                    video_aligned_data[video_name]["points"] = update_points3d\n'
        '                    video_aligned_data[video_name]["colors"] = update_rgb\n'
        "                else:\n"
        '                    video_aligned_data[video_name]["points"] = np.concatenate([video_aligned_data[video_name]["points"], update_points3d], axis=0)\n'
        '                    video_aligned_data[video_name]["colors"] = np.concatenate([video_aligned_data[video_name]["colors"], update_rgb], axis=0)\n'
    )
    aggregate_new = (
        "                # Preserve upstream point order without repeatedly copying\n"
        "                # the full accumulated cloud on every frame.\n"
        '                video_aligned_data[video_name]["point_chunks"].append(update_points3d)\n'
        '                video_aligned_data[video_name]["color_chunks"].append(update_rgb)\n'
    )
    aggregate_finalize_marker = (
        "            n_aligned = len(video_camera_dicts.get(video_name, {}))\n"
    )
    aggregate_finalize = (
        '            point_chunks = video_aligned_data[video_name].pop("point_chunks")\n'
        '            color_chunks = video_aligned_data[video_name].pop("color_chunks")\n'
        "            if point_chunks:\n"
        '                video_aligned_data[video_name]["points"] = np.concatenate(point_chunks, axis=0)\n'
        '                video_aligned_data[video_name]["colors"] = np.concatenate(color_chunks, axis=0)\n'
    )
    if source.count(aggregate_init_old) != 1 or source.count(aggregate_old) != 1:
        raise RuntimeError("expected pinned Phase 6 point aggregation blocks not found")
    if source.count(aggregate_finalize_marker) != 1:
        raise RuntimeError("expected pinned Phase 6 aggregation finalization marker not found")
    source = source.replace(aggregate_init_old, aggregate_init_new, 1)
    source = source.replace(aggregate_old, aggregate_new, 1)
    source = source.replace(
        aggregate_finalize_marker,
        aggregate_finalize + aggregate_finalize_marker,
        1,
    )

    # PNG encoding and filesystem writes are independent per frame. The aligned
    # depth tensor is still copied to the same float32 NumPy array, but Pillow
    # compression/write runs in worker threads while the GPU processes later frames.
    phase6_start = "        abandoned_video_names = set(vname for vname, _ in abandoned_videos)\n"
    depth_save_old = '                save_16bit_png_depth(aligned_depth.cpu().numpy(), f"{save_path}/depths/{fname}.png")\n'
    phase65_marker = "        # Phase 6.5: Filter outlier points after video-level aggregation with Statistical Outlier Removal.\n"
    if source.count(phase6_start) != 1 or source.count(depth_save_old) != 1:
        raise RuntimeError("expected pinned Phase 6 depth-save blocks not found")
    if source.count(phase65_marker) != 1:
        raise RuntimeError("expected pinned Phase 6.5 marker not found")
    source = source.replace(
        phase6_start,
        phase6_start
        + "        _depth_save_executor = ThreadPoolExecutor(max_workers=8)\n"
        + "        _depth_save_futures = collections.deque()\n"
        + "        _depth_save_max_pending = 16\n",
        1,
    )
    source = source.replace(
        depth_save_old,
        "                aligned_depth_np = aligned_depth.cpu().numpy()\n"
        + "                _depth_save_futures.append(\n"
        + "                    _depth_save_executor.submit(\n"
        + '                        save_16bit_png_depth, aligned_depth_np, f"{save_path}/depths/{fname}.png"\n'
        + "                    )\n"
        + "                )\n"
        + "                if len(_depth_save_futures) >= _depth_save_max_pending:\n"
        + "                    _depth_save_futures.popleft().result()\n",
        1,
    )
    source = source.replace(
        phase65_marker,
        "        while _depth_save_futures:\n"
        + "            _depth_save_futures.popleft().result()\n"
        + "        _depth_save_executor.shutdown(wait=True)\n\n"
        + phase65_marker,
        1,
    )

    points_clone_old = (
        "                    self.points.clone(), aligned_depth, rgb_colors, update_mask\n"
    )
    points_clone_new = "                    self.points, aligned_depth, rgb_colors, update_mask\n"
    if source.count(points_clone_old) != 1:
        raise RuntimeError("expected pinned Phase 6 points clone not found")
    source = source.replace(points_clone_old, points_clone_new, 1)
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

    retrieval_path.write_text(source, encoding="utf-8")
