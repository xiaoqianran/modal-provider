from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest
from modal.exception import TimeoutError as ModalTimeoutError
from modal_3d.operations import RESULT_CONTRACT, REVISION

from modal_3d_client import jobs, operation_jobs


class SpawnCall:
    def __init__(self, object_id: str = "fc-operation"):
        self.object_id = object_id


class PendingCall:
    def get(self, timeout=0):
        raise ModalTimeoutError("pending")


class ResultCall:
    def __init__(self, value):
        self.value = value

    def get(self, timeout=0):
        return self.value


class RemoteMethod:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0

    def spawn(self, *args):
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class RemoteObject:
    def __init__(self, method):
        self.run_job = method


class RemoteCls:
    def __init__(self, method):
        self.method = method

    def __call__(self):
        return RemoteObject(self.method)


def service(tmp_path: Path) -> jobs.JobService:
    return jobs.JobService(jobs.JobStore(tmp_path / "jobs.sqlite3"))


def descriptor(sha: str, *, role: str, mime: str = "model/gltf-binary", size: int = 16):
    suffix = ".json" if mime == "application/json" else ".glb"
    return {
        "sha256": sha,
        "bytes": size,
        "mime": mime,
        "role": role,
        "path": f"operations/test/{sha}{suffix}",
        "filename": f"{role}{suffix}",
    }


def bind_remote(monkeypatch, method):
    monkeypatch.setattr(operation_jobs, "client", lambda: object())
    monkeypatch.setattr(
        operation_jobs.modal.Cls,
        "from_name",
        lambda *args, **kwargs: RemoteCls(method),
    )


def test_operation_submit_is_idempotent_and_does_not_spawn_twice(tmp_path, monkeypatch):
    svc = service(tmp_path)
    asset = descriptor("1" * 64, role="primary-glb")
    registered = svc.operations.register(asset)
    method = RemoteMethod(SpawnCall())
    bind_remote(monkeypatch, method)

    first = svc.operations.submit(
        "decimate",
        {"asset": {"artifact_id": registered["id"]}},
        {"target_faces": 120},
        job_id="op_idempotent",
    )
    assert first["status"] == "running"
    assert method.calls == 1

    monkeypatch.setattr(
        operation_jobs.modal.FunctionCall,
        "from_id",
        lambda *args, **kwargs: PendingCall(),
    )
    second = svc.operations.submit(
        "decimate",
        {"asset": {"artifact_id": registered["id"]}},
        {"target_faces": 120},
        job_id="op_idempotent",
    )
    assert second["status"] == "running"
    assert method.calls == 1


def test_unknown_submission_never_blindly_respawns(tmp_path, monkeypatch):
    svc = service(tmp_path)
    asset = descriptor("2" * 64, role="primary-glb")
    registered = svc.operations.register(asset)
    method = RemoteMethod(jobs.ModalConnectionError("lost after submit"))
    bind_remote(monkeypatch, method)

    first = svc.operations.submit(
        "inspect_mesh",
        {"asset": {"artifact_id": registered["id"]}},
        job_id="op_unknown",
    )
    assert first["status"] == "submission_unknown"
    assert first["error_code"] == "remote.submission_unknown"
    assert method.calls == 1

    again = svc.operations.poll("op_unknown")
    assert again["status"] == "submission_unknown"
    assert again["retryable"] is False
    assert method.calls == 1


def test_operation_collects_and_registers_multiple_artifacts(tmp_path, monkeypatch):
    svc = service(tmp_path)
    source = descriptor("3" * 64, role="primary-glb")
    registered = svc.operations.register(source)
    method = RemoteMethod(SpawnCall("fc-results"))
    bind_remote(monkeypatch, method)

    submitted = svc.operations.submit(
        "uv_unwrap",
        {"asset": {"artifact_id": registered["id"]}},
        {"resolution": 128, "padding": 2},
        job_id="op_multi",
    )
    assert submitted["status"] == "running"
    state = svc.operations._get("op_multi")

    artifacts = [
        descriptor("4" * 64, role="primary-glb"),
        descriptor("5" * 64, role="editable-source", mime="model/obj"),
        descriptor("6" * 64, role="uv-mapping", mime="application/json"),
        descriptor("7" * 64, role="quality-report", mime="application/json"),
    ]
    response = {
        "contract": RESULT_CONTRACT,
        "revision": REVISION,
        "operation": "uv_unwrap",
        "request_key": state["request_key"],
        "artifacts": artifacts,
        "metrics": {"uv_atlases": [{"utilization": 0.75}]},
        "timing": {"total_s": 1.2},
    }
    monkeypatch.setattr(
        operation_jobs.modal.FunctionCall,
        "from_id",
        lambda *args, **kwargs: ResultCall(response),
    )

    finished = svc.operations.poll("op_multi")
    assert finished["status"] == "succeeded"
    assert [row["role"] for row in finished["result"]["artifacts"]] == [
        "primary-glb",
        "editable-source",
        "uv-mapping",
        "quality-report",
    ]
    assert all("path" not in row for row in finished["result"]["artifacts"])
    assert svc.operations.asset("art_" + "6" * 64)["role"] == "uv-mapping"


def _minimal_glb() -> bytes:
    document = json.dumps(
        {"asset": {"version": "2.0"}, "meshes": [{"primitives": []}]},
        separators=(",", ":"),
    ).encode()
    document += b" " * ((4 - len(document) % 4) % 4)
    chunk = struct.pack("<I4s", len(document), b"JSON") + document
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunk)) + chunk


def test_operation_artifact_download_checks_size_hash_and_type(tmp_path, monkeypatch):
    svc = service(tmp_path)
    source = descriptor("8" * 64, role="primary-glb")
    registered = svc.operations.register(source)
    method = RemoteMethod(SpawnCall("fc-download"))
    bind_remote(monkeypatch, method)

    svc.operations.submit(
        "inspect_mesh",
        {"asset": {"artifact_id": registered["id"]}},
        job_id="op_download",
    )
    state = svc.operations._get("op_download")
    glb = _minimal_glb()
    sha = hashlib.sha256(glb).hexdigest()
    result_artifacts = [
        descriptor(sha, role="primary-glb", size=len(glb)),
        descriptor("9" * 64, role="quality-report", mime="application/json", size=2),
    ]
    response = {
        "contract": RESULT_CONTRACT,
        "revision": REVISION,
        "operation": "inspect_mesh",
        "request_key": state["request_key"],
        "artifacts": result_artifacts,
        "metrics": {},
        "timing": {},
    }
    monkeypatch.setattr(
        operation_jobs.modal.FunctionCall,
        "from_id",
        lambda *args, **kwargs: ResultCall(response),
    )
    assert svc.operations.poll("op_download")["status"] == "succeeded"

    cache = tmp_path / "cache" / sha
    cache.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(operation_jobs.artifacts, "_cache_path", lambda _sha: cache)
    monkeypatch.setattr(
        operation_jobs.artifacts,
        "_artifact_chunks",
        lambda _path: iter([glb[:17], glb[17:]]),
    )

    public, path = svc.operations.artifact("op_download")
    assert path == cache
    assert path.read_bytes() == glb
    assert public["sha256"] == sha
    assert "path" not in public


def test_same_operation_job_id_rejects_changed_identity(tmp_path, monkeypatch):
    svc = service(tmp_path)
    asset = descriptor("a" * 64, role="primary-glb")
    registered = svc.operations.register(asset)
    method = RemoteMethod(SpawnCall())
    bind_remote(monkeypatch, method)
    svc.operations.submit(
        "decimate",
        {"asset": {"artifact_id": registered["id"]}},
        {"target_faces": 100},
        job_id="op_identity",
    )

    with pytest.raises(ValueError, match="already used"):
        svc.operations.submit(
            "decimate",
            {"asset": {"artifact_id": registered["id"]}},
            {"target_faces": 200},
            job_id="op_identity",
        )
