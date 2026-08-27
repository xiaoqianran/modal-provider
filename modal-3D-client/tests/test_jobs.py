from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from modal_3d_client import artifacts, generation, jobs, models
from modal_3d_client.contracts import ContractError


class Call:
    def __init__(self, value=None):
        self.value = value
        self.cancelled = False

    def get(self, timeout=0):
        return self.value

    def cancel(self):
        self.cancelled = True


class SequenceCall:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.cancelled = False

    def get(self, timeout=0):
        value = next(self.outcomes)
        if isinstance(value, BaseException):
            raise value
        return value

    def cancel(self):
        self.cancelled = True


def service(tmp_path: Path) -> jobs.JobService:
    return jobs.JobService(jobs.JobStore(tmp_path / "jobs.sqlite3"))


def test_submit_is_idempotent_by_job_id(tmp_path, monkeypatch, source_png):
    svc = service(tmp_path)
    sha = hashlib.sha256(source_png).hexdigest()
    monkeypatch.setattr(models, "options_for", lambda *args: {"seed": 42})
    monkeypatch.setattr(
        artifacts,
        "upload_source",
        lambda data: {"path": f"source-inputs/{sha}.png", "sha256": sha, "bytes": len(data)},
    )
    monkeypatch.setattr(
        generation,
        "submit",
        lambda *args: {"model": "fastsam3d-plus-plus", "status": "running", "call_id": "fc_1"},
    )
    first = svc.submit(
        source_png, model="fastsam3d-plus-plus", profile="recommended", job_id="req_1"
    )
    second = svc.submit(
        source_png, model="fastsam3d-plus-plus", profile="recommended", job_id="req_1"
    )
    assert first["id"] == second["id"] == "req_1"
    assert first["status"] == second["status"] == "running"


def test_unknown_submission_rebinds_same_gateway_request(tmp_path, monkeypatch, source_png):
    svc = service(tmp_path)
    sha = hashlib.sha256(source_png).hexdigest()
    monkeypatch.setattr(models, "options_for", lambda *args: {"seed": 42})
    monkeypatch.setattr(
        artifacts,
        "upload_source",
        lambda data: {"path": f"source-inputs/{sha}.png", "sha256": sha, "bytes": len(data)},
    )
    attempts = iter([jobs.ModalConnectionError("lost"), {"call_id": "fc_recovered"}])

    def submit(*args):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return {"model": "fastsam3d-plus-plus", "status": "running", **value}

    monkeypatch.setattr(generation, "submit", submit)
    first = svc.submit(source_png, model="fastsam3d-plus-plus", job_id="req_recover")
    assert first["status"] == "connection_required"
    assert first["retryable"] is True

    monkeypatch.setattr(
        jobs.modal.FunctionCall,
        "from_id",
        lambda *args, **kwargs: Call(
            {"model": "fastsam3d-plus-plus", "artifact": {"placeholder": True}}
        ),
    )
    monkeypatch.setattr(
        artifacts,
        "fetch",
        lambda descriptor, model: (
            {
                "id": "art_ok",
                "role": "primary-glb",
                "mime": "model/gltf-binary",
                "sha256": "a" * 64,
                "bytes": 16,
            },
            tmp_path / "artifact.glb",
        ),
    )
    monkeypatch.setattr(jobs, "client", lambda: object())
    recovered = svc.poll("req_recover")
    assert recovered["status"] == "succeeded"
    stored = svc.store.get("req_recover")
    assert stored.remote_call_id == "fc_recovered"


def test_submit_rejects_same_id_for_different_input(tmp_path, monkeypatch, source_png):
    svc = service(tmp_path)
    monkeypatch.setattr(models, "options_for", lambda *args: {})
    sha = hashlib.sha256(source_png).hexdigest()
    monkeypatch.setattr(
        artifacts,
        "upload_source",
        lambda data: {"path": f"source-inputs/{sha}.png", "sha256": sha, "bytes": len(data)},
    )
    monkeypatch.setattr(
        generation,
        "submit",
        lambda *args: {"model": "fastsam3d-plus-plus", "status": "running", "call_id": "fc_1"},
    )
    svc.submit(source_png, model="fastsam3d-plus-plus", job_id="req_same")
    with pytest.raises(ContractError, match="already bound"):
        svc.submit(
            source_png,
            model="fastsam3d-plus-plus",
            seed=43,
            job_id="req_same",
        )


def test_success_preserves_public_conditioning_evidence_without_provider_path(
    tmp_path, monkeypatch, source_png
):
    svc = service(tmp_path)
    sha = hashlib.sha256(source_png).hexdigest()
    monkeypatch.setattr(models, "options_for", lambda *args: {"seed": 42})
    monkeypatch.setattr(
        artifacts,
        "upload_source",
        lambda data: {"path": f"source-inputs/{sha}.png", "sha256": sha, "bytes": len(data)},
    )
    monkeypatch.setattr(
        generation,
        "submit",
        lambda *args: {"model": "fastsam3d-plus-plus", "status": "running", "call_id": "fc_1"},
    )
    svc.submit(source_png, model="fastsam3d-plus-plus", job_id="req_evidence")
    monkeypatch.setattr(
        jobs.modal.FunctionCall,
        "from_id",
        lambda *args, **kwargs: Call(
            {
                "model": "fastsam3d-plus-plus",
                "artifact": {"placeholder": True},
                "conditioning": {
                    "path": "conditioned-inputs/private.png",
                    "strategy": "birefnet",
                    "engine": "birefnet-general-lite",
                    "source_sha256": sha,
                    "canonical_sha256": "b" * 64,
                    "foreground_ratio": 0.28,
                },
            }
        ),
    )
    monkeypatch.setattr(
        artifacts,
        "fetch",
        lambda descriptor, model: (
            {
                "id": "art_ok",
                "role": "primary-glb",
                "mime": "model/gltf-binary",
                "sha256": "a" * 64,
                "bytes": 16,
            },
            tmp_path / "artifact.glb",
        ),
    )
    monkeypatch.setattr(jobs, "client", lambda: object())

    state = svc.poll("req_evidence")
    assert state["status"] == "succeeded"
    evidence = state["result"]["conditioning"]
    assert evidence["strategy"] == "birefnet"
    assert evidence["engine"] == "birefnet-general-lite"
    assert evidence["source_sha256"] == sha
    assert "path" not in evidence


def test_cancel_requested_survives_timeout_then_becomes_cancelled(
    tmp_path, monkeypatch, source_png
):
    svc = service(tmp_path)
    sha = hashlib.sha256(source_png).hexdigest()
    monkeypatch.setattr(models, "options_for", lambda *args: {"seed": 42})
    monkeypatch.setattr(
        artifacts,
        "upload_source",
        lambda data: {"path": f"source-inputs/{sha}.png", "sha256": sha, "bytes": len(data)},
    )
    monkeypatch.setattr(
        generation,
        "submit",
        lambda *args: {
            "model": "fastsam3d-plus-plus",
            "status": "running",
            "call_id": "fc_cancel",
        },
    )
    state = svc.submit(source_png, model="fastsam3d-plus-plus", job_id="req_cancel")
    assert state["status"] == "running"

    call = SequenceCall(
        [
            jobs.ModalTimeoutError("still running"),
            jobs.RemoteError("remote call cancelled"),
        ]
    )
    monkeypatch.setattr(jobs.modal.FunctionCall, "from_id", lambda *args, **kwargs: call)
    monkeypatch.setattr(jobs, "client", lambda: object())

    cancelled = svc.cancel("req_cancel")
    assert call.cancelled is True
    assert cancelled["status"] == "cancel_requested"

    pending = svc.poll("req_cancel")
    assert pending["status"] == "cancel_requested"
    assert pending["error_code"] is None

    terminal = svc.poll("req_cancel")
    assert terminal["status"] == "cancelled"
    assert terminal["error_code"] == "remote.cancelled"
    assert terminal["retryable"] is False
