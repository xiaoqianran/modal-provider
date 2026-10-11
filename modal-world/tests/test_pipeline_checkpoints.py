"""Checkpoint extraction remains compatible with historical import paths."""
from __future__ import annotations

import json

from modal_world.pipelines import checkpoints
from modal_world import worldgen_job


def test_legacy_checkpoint_exports_are_preserved():
    for name in ("fingerprint_files", "build_stage_manifest", "stage_manifest_path", "manifest_matches", "write_stage_manifest"):
        assert getattr(worldgen_job, name) is getattr(checkpoints, name)


def test_missing_corrupt_and_changed_checkpoints_do_not_resume(tmp_path):
    source = tmp_path / "input.png"
    source.write_bytes(b"initial")
    manifest = checkpoints.build_stage_manifest(
        job_id="run-1", stage="stage3", hyworld_revision="v1",
        input_fingerprint=checkpoints.fingerprint_files([source], root=tmp_path),
        config={"seed": 42},
    )
    assert not checkpoints.manifest_matches(tmp_path, "stage3", manifest)
    path = checkpoints.write_stage_manifest(tmp_path, "stage3", manifest)
    assert checkpoints.manifest_matches(tmp_path, "stage3", manifest)
    path.write_text("{not-json", encoding="utf-8")
    assert not checkpoints.manifest_matches(tmp_path, "stage3", manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    source.write_bytes(b"changed")
    changed = checkpoints.build_stage_manifest(
        job_id="run-1", stage="stage3", hyworld_revision="v1",
        input_fingerprint=checkpoints.fingerprint_files([source], root=tmp_path),
        config={"seed": 42},
    )
    assert not checkpoints.manifest_matches(tmp_path, "stage3", changed)
