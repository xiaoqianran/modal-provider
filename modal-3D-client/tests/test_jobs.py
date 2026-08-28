from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from modal_3d_client import artifacts, generation, jobs, models
from modal_3d_client.contracts import ContractError


class Call:
    def __init__(self, value=None, object_id: str = "fc_1"):
        self.value = value
        self.object_id = object_id
        self.cancelled = False

    def get(self, timeout=0):
        return self.value

    def cancel(self):
        self.cancelled = True


class SequenceCall:
    def __init__(self, outcomes, object_id: str = "fc_1"):
        self.outcomes = iter(outcomes)
        self.object_id = object_id
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


def upload_stub(data: bytes, *, mask: bytes | None = None) -> dict[str, object]:
    """Pretend the source was conditioned locally into a canonical input."""
    sha = hashlib.sha256(data).hexdigest()
    canonical_sha = hashlib.sha256(b"canonical:" + data).hexdigest()
    return {
        "path": f"client-inputs/{canonical_sha}.png",
        "sha256": sha,
        "bytes": len(data),
        "conditioning": {
            "strategy": "preserve-alpha",
            "source_sha256": sha,
            "canonical_sha256": canonical_sha,
            "foreground_ratio": 0.28,
        },
    }


def bind(svc: jobs.JobService, monkeypatch, *, submit=None) -> None:
    monkeypatch.setattr(models, "options_for", lambda *args: {"seed": 42})
    monkeypatch.setattr(artifacts, "upload_source", upload_stub)
    monkeypatch.setattr(generation, "prefetch", lambda *args: Call(object_id="fc_warmup"))
    monkeypatch.setattr(generation, "submit", submit or (lambda *args: Call()))


def test_submit_prefetches_model_before_conditioning_and_generation(tmp_path, monkeypatch, source_png):
    svc = service(tmp_path)
    events = []
    monkeypatch.setattr(models, "options_for", lambda *args: {"seed": 42})
    monkeypatch.setattr(generation, "prefetch", lambda model: events.append(("warmup", model)) or Call())
    monkeypatch.setattr(
        artifacts,
        "upload_source",
        lambda data, *, mask=None: events.append(("condition", mask)) or upload_stub(data, mask=mask),
    )
    monkeypatch.setattr(
        generation,
        "submit",
        lambda *args: events.append(("generate", args[0])) or Call(object_id="fc_generate"),
    )

    state = svc.submit(source_png, model="fastsam3d-plus-plus", job_id="req_parallel_cold_start")

    assert state["status"] == "running"
    assert events == [
        ("warmup", "fastsam3d-plus-plus"),
        ("condition", None),
        ("generate", "fastsam3d-plus-plus"),
    ]


def test_prefetch_connection_failure_is_only_a_latency_miss(tmp_path, monkeypatch, source_png):
    svc = service(tmp_path)
    monkeypatch.setattr(models, "options_for", lambda *args: {"seed": 42})
    monkeypatch.setattr(
        generation,
        "prefetch",
        lambda _model: (_ for _ in ()).throw(jobs.ModalConnectionError("warmup unavailable")),
    )
    monkeypatch.setattr(artifacts, "upload_source", upload_stub)
    monkeypatch.setattr(generation, "submit", lambda *args: Call(object_id="fc_generate"))

    state = svc.submit(source_png, model="fastsam3d-plus-plus", job_id="req_prefetch_best_effort")
    assert state["status"] == "running"
    assert svc.store.get("req_prefetch_best_effort").remote_call_id == "fc_generate"


def test_concurrent_same_job_id_only_prefetches_and_submits_once(
    tmp_path, monkeypatch, source_png
):
    svc = service(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    counts = {"warmup": 0, "upload": 0, "generate": 0}
    count_lock = threading.Lock()

    monkeypatch.setattr(models, "options_for", lambda *args: {"seed": 42})

    def prefetch(_model):
        with count_lock:
            counts["warmup"] += 1
        return Call(object_id="fc_warmup")

    def upload(data, *, mask=None):
        with count_lock:
            counts["upload"] += 1
        entered.set()
        assert release.wait(timeout=2)
        return upload_stub(data, mask=mask)

    def submit(*_args):
        with count_lock:
            counts["generate"] += 1
        return Call(object_id="fc_generate")

    monkeypatch.setattr(generation, "prefetch", prefetch)
    monkeypatch.setattr(artifacts, "upload_source", upload)
    monkeypatch.setattr(generation, "submit", submit)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            svc.submit, source_png, model="fastsam3d-plus-plus", job_id="req_race"
        )
        assert entered.wait(timeout=1)
        second = pool.submit(
            svc.submit, source_png, model="fastsam3d-plus-plus", job_id="req_race"
        )
        time.sleep(0.05)
        release.set()
        first_state = first.result(timeout=2)
        second_state = second.result(timeout=2)

    assert first_state["id"] == second_state["id"] == "req_race"
    assert first_state["status"] == second_state["status"] == "running"
    assert counts == {"warmup": 1, "upload": 1, "generate": 1}
    assert svc._submit_locks == {}


def test_submit_is_idempotent_by_job_id(tmp_path, monkeypatch, source_png):
    svc = service(tmp_path)
    bind(svc, monkeypatch, submit=lambda *args: Call(object_id="fc_1"))
    first = svc.submit(
        source_png, model="fastsam3d-plus-plus", profile="recommended", job_id="req_1"
    )
    second = svc.submit(
        source_png, model="fastsam3d-plus-plus", profile="recommended", job_id="req_1"
    )
    assert first["id"] == second["id"] == "req_1"
    assert first["status"] == second["status"] == "running"


def test_unknown_submission_rebinds_same_worker_request(tmp_path, monkeypatch, source_png):
    svc = service(tmp_path)
    attempts = iter([jobs.ModalConnectionError("lost"), Call(object_id="fc_recovered")])

    def submit(*args):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    bind(svc, monkeypatch, submit=submit)
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
    assert svc.store.get("req_recover").remote_call_id == "fc_recovered"


def test_submit_rejects_same_id_for_different_input(tmp_path, monkeypatch, source_png):
    svc = service(tmp_path)
    bind(svc, monkeypatch)
    svc.submit(source_png, model="fastsam3d-plus-plus", job_id="req_same")
    with pytest.raises(ContractError, match="already bound"):
        svc.submit(
            source_png,
            model="fastsam3d-plus-plus",
            seed=43,
            job_id="req_same",
        )


def test_success_surfaces_locally_produced_conditioning_evidence(
    tmp_path, monkeypatch, source_png
):
    """Conditioning is local now, so it is persisted with the job, not returned by the GPU."""
    svc = service(tmp_path)
    bind(svc, monkeypatch)
    sha = hashlib.sha256(source_png).hexdigest()
    svc.submit(source_png, model="fastsam3d-plus-plus", job_id="req_evidence")

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

    state = svc.poll("req_evidence")
    assert state["status"] == "succeeded"
    evidence = state["conditioning"]
    assert evidence["strategy"] == "preserve-alpha"
    assert evidence["source_sha256"] == sha
    assert "path" not in evidence
    # The GPU result no longer carries conditioning; only the local record does.
    assert "conditioning" not in state["result"]


def test_cancel_requested_survives_timeout_then_becomes_cancelled(
    tmp_path, monkeypatch, source_png
):
    svc = service(tmp_path)
    bind(svc, monkeypatch, submit=lambda *args: Call(object_id="fc_cancel"))
    state = svc.submit(source_png, model="fastsam3d-plus-plus", job_id="req_cancel")
    assert state["status"] == "running"

    call = SequenceCall(
        [
            jobs.ModalTimeoutError("still running"),
            jobs.RemoteError("remote call cancelled"),
        ],
        object_id="fc_cancel",
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


def test_cancel_before_remote_binding_preserves_intent_and_cancels_new_call(
    tmp_path, monkeypatch, source_png
):
    svc = service(tmp_path)
    bound_call = Call()
    monkeypatch.setattr(jobs.modal.FunctionCall, "from_id", lambda *args, **kwargs: bound_call)
    monkeypatch.setattr(jobs, "client", lambda: object())

    def submit(*args):
        pending = svc.cancel("req_submit_cancel")
        assert pending["status"] == "cancel_requested"
        assert pending["error_code"] is None
        return Call(object_id="fc_bound_after_cancel")

    bind(svc, monkeypatch, submit=submit)
    state = svc.submit(source_png, model="fastsam3d-plus-plus", job_id="req_submit_cancel")
    assert state["status"] == "cancel_requested"
    assert svc.store.get("req_submit_cancel").remote_call_id == "fc_bound_after_cancel"
    assert bound_call.cancelled is True


def test_poll_cancel_requested_without_remote_call_waits_without_resubmitting(
    tmp_path, monkeypatch, source_png
):
    svc = service(tmp_path)
    sha = hashlib.sha256(source_png).hexdigest()
    timestamp = jobs._now()
    svc.store.save(
        jobs.Job(
            id="req_local_cancel",
            model="fastsam3d-plus-plus",
            profile="recommended",
            seed=42,
            input_path=f"client-inputs/{sha}.png",
            input_sha256=sha,
            remote_call_id=None,
            status="cancel_requested",
            created_at=timestamp,
            updated_at=timestamp,
            retryable=True,
        )
    )
    monkeypatch.setattr(
        generation,
        "submit",
        lambda *args: pytest.fail("cancelled unbound job must not submit remotely"),
    )
    state = svc.poll("req_local_cancel")
    assert state["status"] == "cancel_requested"
    assert state["error_code"] is None
    assert state["retryable"] is True
