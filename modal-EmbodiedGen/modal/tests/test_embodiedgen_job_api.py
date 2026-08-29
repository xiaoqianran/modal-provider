import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNTIME = ROOT / "runtime" / "embodiedgen_v2_l40s.py"
DIRECT = ROOT / "runtime" / "embodiedgen_direct.py"
spec = importlib.util.spec_from_file_location("embodiedgen_job_api", RUNTIME)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class JobIdentityTest(unittest.TestCase):
    def test_generated_ids_are_unique_and_safe(self):
        first = runtime.new_job_id()
        second = runtime.new_job_id()
        self.assertNotEqual(first, second)
        self.assertTrue(runtime.is_api_job_id(first))
        self.assertTrue(runtime.is_api_job_id(second))

    def test_api_root_rejects_path_escape_and_legacy_ids(self):
        for value in ("../x", "/tmp/x", "bench-20260823T121021-warm", "job-nothex"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.api_job_root(value)

    def test_result_file_map_contains_only_relative_safe_paths(self):
        for value in runtime.ALL_RESULT_FILES.values():
            path = Path(value)
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)



class ArtifactLifecycleTest(unittest.TestCase):
    def test_prune_keeps_only_result_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "result").mkdir()
            (root / "result" / "model.glb").write_bytes(b"glb")
            (root / "validation_report.json").write_text("{}")
            (root / "state.pkl").write_bytes(b"state")
            (root / "nested").mkdir()
            (root / "nested" / "temp").write_text("x")

            removed = runtime.prune_job_intermediates(root)

            self.assertEqual(removed, ["nested", "state.pkl"])
            self.assertTrue((root / "result" / "model.glb").exists())
            self.assertTrue((root / "validation_report.json").exists())

    def test_recent_running_job_does_not_expire(self):
        now = 2_000_000.0
        self.assertFalse(
            runtime.api_job_expired(
                {"status": "running", "updated_epoch": now - runtime.API_ACTIVE_STALE_SECONDS + 1},
                now=now,
                fallback_mtime=0,
            )
        )

    def test_stuck_running_job_expires(self):
        now = 2_000_000.0
        self.assertTrue(
            runtime.api_job_expired(
                {"status": "running", "updated_epoch": now - runtime.API_ACTIVE_STALE_SECONDS - 1},
                now=now,
                fallback_mtime=0,
            )
        )

    def test_failed_and_success_ttls_are_different(self):
        now = 2_000_000.0
        failed = {"status": "failed", "updated_epoch": now - runtime.API_FAILED_TTL_SECONDS - 1}
        succeeded = {
            "status": "succeeded",
            "updated_epoch": now - runtime.API_FAILED_TTL_SECONDS - 1,
        }
        self.assertTrue(runtime.api_job_expired(failed, now=now, fallback_mtime=now))
        self.assertFalse(runtime.api_job_expired(succeeded, now=now, fallback_mtime=now))









class UnifiedRuntimeTest(unittest.TestCase):
    def test_unified_worker_is_single_l40s_cache_boundary(self):
        source = RUNTIME.read_text(encoding="utf-8")
        pos = source.index("class EmbodiedGenWorker:")
        decorator = source[source.rfind("@app.cls(", 0, pos):pos]
        body = source[pos:source.index("\n@app.function(", pos)]
        self.assertIn('gpu="L40S"', decorator)
        self.assertIn('scaledown_window=PIPELINE_SCALEDOWN_SECONDS', decorator)
        self.assertIn('enable_memory_snapshot=True', decorator)
        self.assertIn('experimental_options={"enable_gpu_snapshot": True}', decorator)
        self.assertIn('@modal.enter(snap=True)', body)
        self.assertIn('ort.preload_dlls(cuda=True,cudnn=True,directory="")', body)
        self.assertIn('ort.InferenceSession(str(BIREFNET_MODEL_PATH),providers=providers)', body)
        self.assertIn('self.pipeline=Sam3dInference', body)
        self.assertNotIn('rembg.session_factory', body)
        self.assertIn('patch_sam3d_local_only.py', source)
        self.assertIn('patch_sam3d_snapshot_cpu.py', source)

    def test_pipeline_stages_stay_in_one_method_and_in_order(self):
        source = RUNTIME.read_text(encoding="utf-8")
        start = source.index("class EmbodiedGenWorker:")
        end = source.index("\n@app.function(", start)
        body = source[start:end]
        markers = [
            '_job_stage(job_id,"rembg"',
            '_job_stage(job_id,"sam3d"',
            '_job_stage(job_id,"mesh"',
            '_job_stage(job_id,"texture"',
            '_job_stage(job_id,"finalize"',
        ]
        positions = [body.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(body.count("artifacts.commit()"), 1)
        self.assertNotIn("artifacts.reload()", body)
        self.assertNotIn("state_handoff", body)

    def test_legacy_split_workers_are_gone(self):
        runtime_source = RUNTIME.read_text(encoding="utf-8")
        direct_source = DIRECT.read_text(encoding="utf-8")
        for old in (
            "class RembgWorker:",
            "class Sam3DWorker:",
            "class MeshWorker:",
            "def lite_gpu_bake(",
            "def cpu_finalize(",
            "state_handoff",
            "apply_autoscale_profile",
            "update_autoscaler",
        ):
            self.assertNotIn(old, runtime_source)
        self.assertNotIn('modal.Cls.from_name(APP_NAME, "RembgWorker")', direct_source)
        self.assertNotIn('modal.Cls.from_name(APP_NAME, "Sam3DWorker")', direct_source)
        self.assertIn('modal.Cls.from_name(APP_NAME, "EmbodiedGenWorker")', direct_source)

    def test_image_submit_spawns_unified_worker_without_volume_bus(self):
        source = DIRECT.read_text(encoding="utf-8")
        start = source.index("def submit_image3d(")
        end = source.index("def _wait_job(", start)
        body = source[start:end]
        self.assertIn("path.read_bytes()", body)
        self.assertIn("_pipeline_worker().generate.spawn(job_id, data, int(seed))", body)
        self.assertNotIn("batch_upload", body)
        self.assertNotIn("update_autoscaler", body)

    def test_unified_benchmark_requires_same_resident_instance(self):
        source = RUNTIME.read_text(encoding="utf-8")
        start = source.index("def benchmark_unified(")
        body = source[start:]
        self.assertIn('for label in ("cold", "warm")', body)
        self.assertIn('runs[0]["instance_id"] != runs[1]["instance_id"]', body)
        self.assertIn("UNIFIED_BENCHMARK_OK", body)


class TextJobTest(unittest.TestCase):
    def test_prompt_validation(self):
        self.assertEqual(runtime.normalize_text_prompt("  red mug  "), "red mug")
        with self.assertRaises(TypeError):
            runtime.normalize_text_prompt(None)
        for value in ("", "   ", "x" * (runtime.MAX_PROMPT_CHARS + 1)):
            with self.subTest(value=value[:16]), self.assertRaises(ValueError):
                runtime.normalize_text_prompt(value)

    def test_text_worker_is_l40s_offline_handoff_worker(self):
        source = RUNTIME.read_text(encoding="utf-8")
        pos = source.index("class Text2ImageWorker:")
        decorator = source[source.rfind("@app.cls(", 0, pos):pos]
        body_end = source.index("class RetextureWorker:", pos)
        body = source[pos:body_end]
        self.assertIn('gpu="L40S"', decorator)
        self.assertIn('scaledown_window=TEXT2IMG_SCALEDOWN_SECONDS', decorator)
        self.assertNotIn('enable_memory_snapshot=True', decorator)
        self.assertNotIn('@modal.enter(snap=True)', body)
        self.assertIn('local_files_only=True', body)
        self.assertIn('HF_HUB_OFFLINE', body)
        self.assertIn('TRANSFORMERS_OFFLINE', body)
        self.assertIn('modal.Cls.from_name(APP_NAME,"EmbodiedGenWorker")', body)
        self.assertIn('worker.generate.spawn(job_id,png,seed)', body)

    def test_text_submit_returns_job_without_vps_png_round_trip(self):
        source = DIRECT.read_text(encoding="utf-8")
        start = source.index("def submit_text3d(")
        end = source.index("def generate_text3d(", start)
        body = source[start:end]
        self.assertIn('text.generate.spawn(job_id, prompt, seed, True)', body)
        self.assertNotIn("image_bytes", body)
        self.assertNotIn("threading", body)
        self.assertNotIn(".remote(", body)


class RetextureJobTest(unittest.TestCase):
    def test_retexture_worker_is_single_l40s_offline_pipeline(self):
        source = RUNTIME.read_text(encoding="utf-8")
        pos = source.index("class RetextureWorker:")
        decorator = source[source.rfind("@app.cls(", 0, pos):pos]
        end = source.index("def _job_stage", pos)
        body = source[pos:end]
        self.assertIn('gpu="L40S"', decorator)
        self.assertIn('scaledown_window=RETEXTURE_SCALEDOWN_SECONDS', decorator)
        self.assertIn('local_files_only=True', body)
        self.assertIn('HF_HUB_OFFLINE', body)
        self.assertIn('delight=False', body)
        self.assertIn('ip_adapt_scale=0.0', body)

    def test_retexture_validates_geometry_preservation(self):
        source = RUNTIME.read_text(encoding="utf-8")
        pos = source.index("class RetextureWorker:")
        end = source.index("def _job_stage", pos)
        body = source[pos:end]
        self.assertIn('source_geometry_preserved', body)
        self.assertIn('np.allclose(src_mesh.bounds,objm.bounds', body)
        self.assertIn('len(src_mesh.faces)==len(objm.faces)', body)

    def test_retexture_is_direct_from_local_control_plane(self):
        source = DIRECT.read_text(encoding="utf-8")
        start = source.index("def retexture(")
        end = source.index("def normalize_affordance_options(", start)
        body = source[start:end]
        self.assertIn('source.get("status") != "succeeded"', body)
        self.assertIn('modal.Cls.from_name(APP_NAME, "RetextureWorker")', body)
        self.assertIn('worker.generate.remote(job_id, source_job_id, prompt, seed)', body)
        self.assertNotIn("update_autoscaler", body)


class AffordanceJobTest(unittest.TestCase):
    def test_affordance_options_are_strict_and_defaulted(self):
        options = runtime.normalize_affordance_options({})
        self.assertEqual(options["profile"], "part-evidence-only")
        self.assertEqual(options["point_num"], 20000)
        self.assertEqual(options["topk"], 20)
        semantic = runtime.normalize_affordance_options({"profile": "semantic-evidence-v1", "category": " mug "})
        self.assertEqual(semantic["profile"], "semantic-evidence-v1")
        self.assertEqual(semantic["category"], "mug")
        with self.assertRaises(ValueError):
            runtime.normalize_affordance_options({"profile": "full"})
        with self.assertRaises(ValueError):
            runtime.normalize_affordance_options({"category": "mug"})
        with self.assertRaises(ValueError):
            runtime.normalize_affordance_options({"topk": 81, "num_grasps": 80})
        with self.assertRaises(TypeError):
            runtime.normalize_affordance_options({"seed": True})
        with self.assertRaises(ValueError):
            runtime.normalize_affordance_options({"semantic": True})

    def test_affordance_direct_control_uses_separate_apps_and_stage_order(self):
        source = DIRECT.read_text(encoding="utf-8")
        self.assertIn('AFFORDANCE_APP_NAME = "modal-3d-embodiedgen-affordance"', source)
        self.assertIn('modal.Function.from_name(AFFORDANCE_APP_NAME, "segment_job")', source)
        self.assertIn('modal.Function.from_name(AFFORDANCE_APP_NAME, "raw_grasp_job")', source)
        start = source.index("def generate_affordance(")
        end = source.index("def download_result(", start)
        body = source[start:end]
        self.assertLess(body.index('"segment"'), body.index('"grasp_raw"'))
        self.assertLess(body.index('"grasp_raw"'), body.index('"finalize"'))
        self.assertIn('"semantic_inputs"', body)
        self.assertIn('"semantic_annotate"', body)
        self.assertIn("output_job_id=job_id", body)
        self.assertNotIn("spawn(", body)
    def test_affordance_finalize_publishes_hash_bound_bundle(self):
        source = RUNTIME.read_text(encoding="utf-8")
        start = source.index("def finalize_affordance_bundle(")
        end = source.index("@app.function(", start)
        body = source[start:end]
        self.assertIn('"version": 1', body)
        self.assertIn('"provider": "embodiedgen"', body)
        self.assertIn('"role": role', body)
        self.assertIn('segmentation.get("artifact", {}).get("sha256") != primary_sha256', body)
        self.assertIn('raw_grasps.get("evidence_level") != "raw"', body)
        self.assertIn('AFFORDANCE_PART_EVIDENCE_BUNDLE_OK', body)
        self.assertIn('AFFORDANCE_SEMANTIC_EVIDENCE_BUNDLE_OK', body)
        self.assertIn('"part_semantics"', body)
        self.assertIn('part semantics IDs do not match segmentation IDs', body)
        self.assertIn('part semantics validation SHA mismatch', body)
        self.assertIn('forbidden executable fields', body)
        self.assertNotIn('sapien_grasps', body)

    def test_affordance_result_files_are_profile_scoped(self):
        base = runtime.affordance_result_files("part-evidence-only")
        semantic = runtime.affordance_result_files("semantic-evidence-v1")
        self.assertNotIn("part_semantics", base)
        self.assertIn("part_semantics", semantic)
        self.assertIn("semantic_inputs", semantic)
        self.assertEqual(base["affordance_bundle"], semantic["affordance_bundle"])
        with self.assertRaises(ValueError):
            runtime.affordance_result_files("unknown")

    def test_affordance_has_no_modal_api_dispatch_layer(self):
        runtime_source = RUNTIME.read_text(encoding="utf-8")
        direct_source = DIRECT.read_text(encoding="utf-8")
        self.assertNotIn("def run_affordance_job(", runtime_source)
        self.assertNotIn("@modal.asgi_app", runtime_source)
        self.assertIn("def generate_affordance(", direct_source)
        self.assertIn("_put_job(", direct_source)
    def test_direct_download_is_scoped_to_state_file_roles(self):
        source = DIRECT.read_text(encoding="utf-8")
        start = source.index("def download_result(")
        body = source[start:]
        self.assertIn('state.get("files")', body)
        self.assertIn("RESULT_FILES", body)
        self.assertIn("AFFORDANCE_RESULT_FILES", body)
        self.assertIn("_artifacts().read_file(remote)", body)

class AffordanceSemanticInputTest(unittest.TestCase):
    def test_semantic_parts_are_bound_to_persisted_provider_palette(self):
        parts = runtime.semantic_parts_from_segmentation(
            {
                "palette": [
                    {"id": "0", "name": "Red", "rgb": [230, 25, 75]},
                    {"id": "1", "name": "Green", "rgb": [60, 180, 75]},
                ]
            },
            {"segments": [{"id": "1", "faceCount": 2}, {"id": "0", "faceCount": 3}]},
        )
        self.assertEqual(parts, [
            {"id": "1", "maskColor": "Green", "maskRgb": [60, 180, 75]},
            {"id": "0", "maskColor": "Red", "maskRgb": [230, 25, 75]},
        ])
        with self.assertRaises(ValueError):
            runtime.semantic_parts_from_segmentation(
                {"palette": [{"id": "0", "name": "Red", "rgb": [230, 25, 75]}]},
                {"segments": [{"id": "1", "faceCount": 2}]},
            )

    def test_semantic_input_renderer_is_isolated_from_gpt_and_hash_binds_outputs(self):
        source = RUNTIME.read_text(encoding="utf-8")
        start = source.index("def prepare_affordance_semantic_inputs(")
        end = source.index("\n@app.function(", start)
        body = source[start:end]
        self.assertIn('gpu="L40S"', source[source.rfind("@app.function", 0, start):start])
        self.assertIn('from embodied_gen.utils.vis_utils import render_grid', body)
        self.assertIn('output_subdir="rgb_views"', body)
        self.assertIn('staging / "mask_views"', body)
        self.assertIn('render_semantic_face_label_grid(', body)
        self.assertIn('compiler_segmentation,', body)
        self.assertIn('semantic_grid_diagnostics(mask_final)', body)
        self.assertIn('semantic_mask_palette_visibility(mask_final, parts)', body)
        self.assertIn('render_semantic_part_atlas(', body)
        self.assertIn('"partAtlas": {', body)
        self.assertIn('"renderer": "embodiedgen-rgb+nvdiffrast-face-id"', body)
        self.assertIn('semantic_mask_palette_visibility(mask_final, parts)', body)
        self.assertIn('"sha256": _sha256_file(rgb_final)', body)
        self.assertIn('"sha256": _sha256_file(mask_final)', body)
        self.assertIn('semantic_parts_from_segmentation', body)
        self.assertIn('AFFORDANCE_SEMANTIC_INPUTS_OK', body)
        self.assertNotIn('API_KEY', body)
        self.assertNotIn('MODEL_NAME', body)
        self.assertNotIn('openai', body.lower())

    def test_semantic_mask_uses_triangle_id_raster_not_materials(self):
        source = RUNTIME.read_text(encoding="utf-8")
        start = source.index("def render_semantic_face_label_grid(")
        end = source.index("def new_job_id", start)
        body = source[start:end]
        self.assertIn('rast[..., 3].long() - 1', body)
        self.assertIn('image[valid] = colors[ids[valid]]', body)
        self.assertIn('CameraSetting(', body)
        self.assertIn('elevation=(45.0, -45.0)', body)
        self.assertIn('distance=5.0', body)
        self.assertIn('fov=math.radians(30.0)', body)
        self.assertIn('render_semantic_face_label_grid', source)
        self.assertNotIn('map_Kd', body)
        self.assertNotIn('mask_obj', body)

    def test_semantic_part_atlas_isolated_views_cover_hidden_parts(self):
        source = RUNTIME.read_text(encoding="utf-8")
        start = source.index("def render_semantic_part_atlas(")
        end = source.index("def new_job_id", start)
        body = source[start:end]
        self.assertIn('views_per_part: int = 3', body)
        self.assertIn('torch.unique(', body)
        self.assertIn('normalize_vertices_array(part_vertices)', body)
        self.assertIn('semantic part atlas cannot render part', body)
        self.assertIn("part {part_id}  {part['maskColor']}", body)

    def test_semantic_category_is_bounded(self):
        self.assertEqual(runtime.normalize_semantic_category(" mug "), "mug")
        with self.assertRaises(ValueError):
            runtime.normalize_semantic_category("")
        with self.assertRaises(ValueError):
            runtime.normalize_semantic_category("x" * 161)






if __name__ == "__main__":
    unittest.main()
