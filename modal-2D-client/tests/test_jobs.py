from pathlib import Path

import pytest

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


def test_explicit_job_id_is_durable_across_restart(tmp_path: Path, monkeypatch):
    submit = SubmitFunction()
    monkeypatch.setattr(jobs.capabilities, "ensure_model", lambda model: None)
    monkeypatch.setattr(jobs, "client", lambda: object())
    monkeypatch.setattr(jobs.modal.Function, "from_name", lambda *args, **kwargs: submit)

    db = tmp_path / "jobs.sqlite3"
    created = jobs.JobService(jobs.JobStore(db)).submit(
        {"prompt": "mossy house"},
        job_id="job_connector_2d",
    )

    assert created["id"] == "job_connector_2d"
    restored = jobs.JobStore(db).get("job_connector_2d")
    assert restored.remote_call_id == "fc-remote-01"
    assert restored.status == "running"


def test_unknown_submission_is_durable_and_never_replayed(tmp_path: Path, monkeypatch):
    class UncertainSubmit:
        calls = 0

        def spawn(self, payload):
            self.calls += 1
            raise RuntimeError("response lost after remote submission")

    submit = UncertainSubmit()
    monkeypatch.setattr(jobs.capabilities, "ensure_model", lambda model: None)
    monkeypatch.setattr(jobs, "client", lambda: object())
    monkeypatch.setattr(jobs.modal.Function, "from_name", lambda *args, **kwargs: submit)

    db = tmp_path / "jobs.sqlite3"
    service = jobs.JobService(jobs.JobStore(db))
    created = service.submit({"prompt": "x"}, job_id="job_connector_unknown")

    assert created["status"] == "connection_required"
    assert created["error_code"] == "remote.submission_unknown"
    assert created["retryable"] is False
    assert submit.calls == 1

    restarted = jobs.JobService(jobs.JobStore(db))
    recovered = restarted.poll("job_connector_unknown")
    assert recovered == created
    with pytest.raises(jobs.ContractError, match="already exists"):
        restarted.submit({"prompt": "x"}, job_id="job_connector_unknown")
    assert submit.calls == 1


def test_submitting_placeholder_recovers_fail_closed_after_crash(tmp_path: Path):
    db = tmp_path / "jobs.sqlite3"
    store = jobs.JobStore(db)
    now = "2026-08-26T00:00:00+00:00"
    store.save(
        jobs.Job(
            id="job_crash_window",
            model="sana-sprint-1.6b",
            remote_call_id=None,
            status="submitting",
            created_at=now,
            updated_at=now,
            retryable=False,
        )
    )

    recovered = jobs.JobService(jobs.JobStore(db)).poll("job_crash_window")

    assert recovered["status"] == "connection_required"
    assert recovered["error_code"] == "remote.submission_unknown"
    assert recovered["retryable"] is False


def test_v1_database_migrates_remote_call_id_to_nullable(tmp_path: Path):
    db_path = tmp_path / "legacy.sqlite3"
    import sqlite3

    with sqlite3.connect(db_path) as db, db:
        db.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, model TEXT NOT NULL, remote_call_id TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                result_json TEXT, error_code TEXT, retryable INTEGER
            )
            """
        )
        db.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "job_old",
                "sana-sprint-1.6b",
                "fc-old",
                "running",
                "2026-08-26T00:00:00+00:00",
                "2026-08-26T00:00:00+00:00",
                None,
                None,
                1,
            ),
        )
        db.execute("PRAGMA user_version = 1")

    store = jobs.JobStore(db_path)
    assert store.get("job_old").remote_call_id == "fc-old"
    with sqlite3.connect(db_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        remote = next(
            row
            for row in db.execute("PRAGMA table_info(jobs)")
            if row[1] == "remote_call_id"
        )
        assert remote[3] == 0


def test_incompatible_or_future_database_is_rejected(tmp_path: Path):
    import sqlite3

    broken = tmp_path / "broken.sqlite3"
    with sqlite3.connect(broken) as db, db:
        db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, remote_call_id TEXT)")
    with pytest.raises(RuntimeError, match="schema is incompatible"):
        jobs.JobStore(broken)

    future = tmp_path / "future.sqlite3"
    with sqlite3.connect(future) as db, db:
        db.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError, match="newer than supported"):
        jobs.JobStore(future)


def test_cancel_during_spawn_preserves_intent_and_cancels_bound_remote(
    tmp_path: Path, monkeypatch
):
    poll = PollCall()
    service_holder = {}

    class CancelDuringSpawn:
        def spawn(self, payload):
            pending = service_holder["service"].cancel("job_cancel_during_spawn")
            assert pending["status"] == "cancel_requested"
            assert pending["error_code"] is None
            return SpawnCall()

    monkeypatch.setattr(jobs.capabilities, "ensure_model", lambda model: None)
    monkeypatch.setattr(jobs, "client", lambda: object())
    monkeypatch.setattr(
        jobs.modal.Function, "from_name", lambda *args, **kwargs: CancelDuringSpawn()
    )
    monkeypatch.setattr(
        jobs.modal.FunctionCall, "from_id", lambda *args, **kwargs: poll
    )

    service = jobs.JobService(jobs.JobStore(tmp_path / "jobs.sqlite3"))
    service_holder["service"] = service
    state = service.submit({"prompt": "x"}, job_id="job_cancel_during_spawn")

    assert state["status"] == "cancel_requested"
    assert state["error_code"] is None
    assert poll.cancelled is True
    stored = service.store.get("job_cancel_during_spawn")
    assert stored.remote_call_id == "fc-remote-01"


def test_cancel_requested_without_remote_id_stays_pending_without_resubmit(
    tmp_path: Path, monkeypatch
):
    store = jobs.JobStore(tmp_path / "jobs.sqlite3")
    now = "2026-08-28T00:00:00+00:00"
    store.save(
        jobs.Job(
            id="job_pending_cancel",
            model="sana-sprint-1.6b",
            remote_call_id=None,
            status="cancel_requested",
            created_at=now,
            updated_at=now,
            retryable=True,
        )
    )
    monkeypatch.setattr(
        jobs.modal.Function,
        "from_name",
        lambda *args, **kwargs: pytest.fail("cancel_requested job must not resubmit"),
    )

    state = jobs.JobService(store).poll("job_pending_cancel")
    assert state["status"] == "cancel_requested"
    assert state["error_code"] is None
    assert state["retryable"] is True
