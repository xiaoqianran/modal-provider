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


def service(tmp_path: Path) -> jobs.JobService:
    return jobs.JobService(jobs.JobStore(tmp_path / "jobs.sqlite3"))


def test_submit_is_idempotent_by_job_id(tmp_path, monkeypatch, canonical_png):
    svc = service(tmp_path)
    sha = hashlib.sha256(canonical_png).hexdigest()
    monkeypatch.setattr(models, "options_for", lambda *args: {"seed": 42})
    monkeypatch.setattr(
        artifacts,
        "upload_canonical",
        lambda data: {"path": f"client-inputs/{sha}.png", "sha256": sha, "bytes": len(data)},
    )
    monkeypatch.setattr(
        generation,
        "submit",
        lambda *args: {"model": "fastsam3d-plus-plus", "status": "running", "call_id": "fc_1"},
    )
    first = svc.submit(
        canonical_png, model="fastsam3d-plus-plus", profile="recommended", job_id="req_1"
    )
    second = svc.submit(
        canonical_png, model="fastsam3d-plus-plus", profile="recommended", job_id="req_1"
    )
    assert first["id"] == second["id"] == "req_1"
    assert first["status"] == second["status"] == "running"


def test_unknown_submission_rebinds_same_gateway_request(tmp_path, monkeypatch, canonical_png):
    svc = service(tmp_path)
    sha = hashlib.sha256(canonical_png).hexdigest()
    monkeypatch.setattr(models, "options_for", lambda *args: {"seed": 42})
    monkeypatch.setattr(
        artifacts,
        "upload_canonical",
        lambda data: {"path": f"client-inputs/{sha}.png", "sha256": sha, "bytes": len(data)},
    )
    attempts = iter([jobs.ModalConnectionError("lost"), {"call_id": "fc_recovered"}])

    def submit(*args):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return {"model": "fastsam3d-plus-plus", "status": "running", **value}

    monkeypatch.setattr(generation, "submit", submit)
    first = svc.submit(canonical_png, model="fastsam3d-plus-plus", job_id="req_recover")
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


def test_submit_rejects_same_id_for_different_input(tmp_path, monkeypatch, canonical_png):
    svc = service(tmp_path)
    monkeypatch.setattr(models, "options_for", lambda *args: {})
    sha = hashlib.sha256(canonical_png).hexdigest()
    monkeypatch.setattr(
        artifacts,
        "upload_canonical",
        lambda data: {"path": f"client-inputs/{sha}.png", "sha256": sha, "bytes": len(data)},
    )
    monkeypatch.setattr(
        generation,
        "submit",
        lambda *args: {"model": "fastsam3d-plus-plus", "status": "running", "call_id": "fc_1"},
    )
    svc.submit(canonical_png, model="fastsam3d-plus-plus", job_id="req_same")
    with pytest.raises(ContractError, match="already bound"):
        svc.submit(
            canonical_png,
            model="fastsam3d-plus-plus",
            seed=43,
            job_id="req_same",
        )
