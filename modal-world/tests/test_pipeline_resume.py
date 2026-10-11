"""CPU-only resume policy tests, including safe legacy adoption."""
from __future__ import annotations

from modal_world.pipelines.checkpoints import build_stage_manifest, write_stage_manifest
from modal_world.pipelines.resume import decide_resume


def expected():
    return build_stage_manifest(job_id="case000", stage="stage2", hyworld_revision="rev1", input_fingerprint="hash1", config={"seed": 42})


def test_missing_manifest_legacy_adoption_only_for_case000(tmp_path):
    assert decide_resume(tmp_path, "stage2", expected(), job_id="case000").adopt_legacy
    assert not decide_resume(tmp_path, "stage2", expected(), job_id="job-2").reuse
    assert not decide_resume(tmp_path, "stage2", expected(), job_id="case000", allow_legacy=False).reuse


def test_exact_manifest_reuse_and_force_is_handled_by_caller(tmp_path):
    manifest = expected()
    write_stage_manifest(tmp_path, "stage2", manifest)
    decision = decide_resume(tmp_path, "stage2", manifest, job_id="job-2")
    assert decision.reuse and not decision.adopt_legacy


def test_existing_stale_or_corrupt_manifest_never_adopted(tmp_path):
    path = write_stage_manifest(tmp_path, "stage2", expected())
    stale = {**expected(), "input_fingerprint": "changed"}
    assert not decide_resume(tmp_path, "stage2", stale, job_id="case000").reuse
    path.write_text("invalid-json", encoding="utf-8")
    assert not decide_resume(tmp_path, "stage2", expected(), job_id="case000").reuse


def test_manifest_isolation_by_stage(tmp_path):
    write_stage_manifest(tmp_path, "stage1", expected())
    assert not decide_resume(tmp_path, "stage2", expected(), job_id="other-job").reuse
