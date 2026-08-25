from pathlib import Path

from modal_2d_client import jobs


class SpawnCall:
    object_id = "fc-remote-01"


class SubmitFunction:
    def __init__(self):
        self.payload = None

    def spawn(self, payload):
        self.payload = payload
        return SpawnCall()


class PollCall:
    def __init__(self, result=None):
        self.result = result
        self.cancelled = False

    def get(self, timeout=0):
        return self.result

    def cancel(self):
        self.cancelled = True


class FailingPollCall:
    def get(self, timeout=0):
        raise ValueError("provider rejected runtime input")


def test_job_submit_poll_and_persistence(tmp_path: Path, monkeypatch, png_artifact):
    _, descriptor = png_artifact
    submit = SubmitFunction()
    poll = PollCall({"model": "sana-sprint-1.6b", "artifact": descriptor})
    monkeypatch.setattr(jobs.capabilities, "ensure_model", lambda model: None)
    monkeypatch.setattr(jobs, "client", lambda: object())
    monkeypatch.setattr(jobs.modal.Function, "from_name", lambda *args, **kwargs: submit)
    monkeypatch.setattr(jobs.modal.FunctionCall, "from_id", lambda *args, **kwargs: poll)

    store = jobs.JobStore(tmp_path / "jobs.sqlite3")
    service = jobs.JobService(store)
    created = service.submit({"prompt": "mossy house"})
    assert created["status"] == "running"
    assert submit.payload == {"prompt": "mossy house", "model": "sana-sprint-1.6b", "seed": 42}

    finished = service.poll(created["id"])
    assert finished["status"] == "succeeded"
    assert finished["result"]["artifact"]["id"] == "art_abc"

    restored = jobs.JobStore(tmp_path / "jobs.sqlite3").get(created["id"])
    assert restored.remote_call_id == "fc-remote-01"
    assert restored.status == "succeeded"


def test_cancel_is_non_terminal_until_remote_ack(tmp_path: Path, monkeypatch):
    submit = SubmitFunction()
    poll = PollCall()
    monkeypatch.setattr(jobs.capabilities, "ensure_model", lambda model: None)
    monkeypatch.setattr(jobs, "client", lambda: object())
    monkeypatch.setattr(jobs.modal.Function, "from_name", lambda *args, **kwargs: submit)
    monkeypatch.setattr(jobs.modal.FunctionCall, "from_id", lambda *args, **kwargs: poll)

    service = jobs.JobService(jobs.JobStore(tmp_path / "jobs.sqlite3"))
    created = service.submit({"prompt": "x"})
    cancelled = service.cancel(created["id"])
    assert cancelled["status"] == "cancel_requested"
    assert poll.cancelled is True


def test_artifact_download_is_lazy(tmp_path: Path, monkeypatch, png_artifact):
    _, descriptor = png_artifact
    store = jobs.JobStore(tmp_path / "jobs.sqlite3")
    job = jobs.Job(
        id="job_01",
        model="sana-sprint-1.6b",
        remote_call_id="fc-01",
        status="succeeded",
        created_at="2026-08-25T00:00:00+00:00",
        updated_at="2026-08-25T00:00:00+00:00",
        result={"artifact": descriptor},
        retryable=False,
    )
    store.save(job)
    expected = tmp_path / "cached.png"
    expected.write_bytes(b"png")
    calls = []
    monkeypatch.setattr(
        jobs.artifacts, "fetch", lambda value: calls.append(value["id"]) or expected
    )

    returned_descriptor, path = jobs.JobService(store).artifact("job_01")
    assert returned_descriptor["id"] == "art_abc"
    assert path == expected
    assert calls == ["art_abc"]


def test_remote_model_exception_is_execution_failed(tmp_path: Path, monkeypatch):
    submit = SubmitFunction()
    monkeypatch.setattr(jobs.capabilities, "ensure_model", lambda model: None)
    monkeypatch.setattr(jobs, "client", lambda: object())
    monkeypatch.setattr(jobs.modal.Function, "from_name", lambda *args, **kwargs: submit)
    monkeypatch.setattr(
        jobs.modal.FunctionCall, "from_id", lambda *args, **kwargs: FailingPollCall()
    )

    service = jobs.JobService(jobs.JobStore(tmp_path / "jobs.sqlite3"))
    created = service.submit({"prompt": "x"})
    failed = service.poll(created["id"])

    assert failed["status"] == "failed"
    assert failed["error_code"] == "remote.execution_failed"
    assert failed["retryable"] is False
