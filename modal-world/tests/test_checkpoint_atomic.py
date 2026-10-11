"""CPU-only atomic checkpoint persistence tests."""
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from modal_world.pipelines.checkpoints import (
    build_stage_manifest,
    fingerprint_files,
    manifest_matches,
    stage_manifest_path,
    write_stage_manifest,
)


def manifest(revision):
    return build_stage_manifest(job_id="job-1", stage="stage3", hyworld_revision=str(revision), input_fingerprint=str(revision), config={"seed": 42})


def test_replace_failure_preserves_old_checkpoint(tmp_path):
    path = write_stage_manifest(tmp_path, "stage3", manifest("old"))
    before = path.read_bytes()
    with (
        patch("modal_world.pipelines.checkpoints.os.replace", side_effect=OSError("failed")),
        pytest.raises(OSError, match="failed"),
    ):
            write_stage_manifest(tmp_path, "stage3", manifest("new"))
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


def test_serialization_error_does_not_truncate_checkpoint(tmp_path):
    path = write_stage_manifest(tmp_path, "stage3", manifest("old"))
    with pytest.raises(TypeError):
        write_stage_manifest(tmp_path, "stage3", {"invalid": object()})
    assert manifest_matches(tmp_path, "stage3", manifest("old"))
    assert not list(path.parent.glob("*.tmp"))


def test_concurrent_writers_produce_only_valid_complete_documents(tmp_path):
    versions = [manifest(i) for i in range(20)]
    path = stage_manifest_path(tmp_path, "stage3")

    def write_read(version):
        write_stage_manifest(tmp_path, "stage3", version)
        return json.loads(path.read_text(encoding="utf-8"))

    with ThreadPoolExecutor(max_workers=8) as executor:
        observed = list(executor.map(write_read, versions))
    assert all(item in versions for item in observed)
    assert json.loads(path.read_text(encoding="utf-8")) in versions
    assert not list(path.parent.glob("*.tmp"))


def test_input_change_invalidates_downstream_manifest(tmp_path):
    source = tmp_path / "upstream.bin"
    source.write_bytes(b"old")
    old = build_stage_manifest(job_id="job-1", stage="stage4", hyworld_revision="v1", input_fingerprint=fingerprint_files([source], root=tmp_path), config={})
    write_stage_manifest(tmp_path, "stage4", old)
    source.write_bytes(b"new")
    changed = {**old, "input_fingerprint": fingerprint_files([source], root=tmp_path)}
    assert not manifest_matches(tmp_path, "stage4", changed)
