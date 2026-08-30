from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from modal_gen.deployments import DeploymentService, DeploymentTarget


def _wait(service: DeploymentService, job_id: str, timeout: float = 3.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.deployment_job(job_id)
        if job["status"] in {"succeeded", "partial", "failed"}:
            return job
        time.sleep(0.01)
    raise AssertionError("deployment job did not finish")


def test_start_deploy_returns_job_and_runs_in_background(monkeypatch):
    target = DeploymentTarget("modal-2d", "worker", "runtime.worker")
    service = DeploymentService(targets=(target,))
    service._client = SimpleNamespace()
    release = threading.Event()

    class App:
        def deploy(self, **_kwargs):
            release.wait(2)
            return self

        def get_tags(self, **_kwargs):
            return {}

        def set_tags(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "modal_gen.deployments.importlib.import_module",
        lambda _name: SimpleNamespace(app=App()),
    )
    job = service.start_deploy("modal-2d")
    assert job["id"].startswith("dep_")
    assert job["status"] in {"queued", "running"}
    release.set()
    finished = _wait(service, str(job["id"]))
    assert finished["status"] == "succeeded"
    assert finished["result"]["providers"][0]["apps"][0]["status"] == "current"


def test_deployment_executor_caps_concurrency_at_two(monkeypatch):
    targets = tuple(
        DeploymentTarget("modal-2d", f"app-{index}", f"runtime.{index}") for index in range(4)
    )
    service = DeploymentService(targets=targets, max_workers=2)
    service._client = SimpleNamespace()
    lock = threading.Lock()
    active = 0
    peak = 0
    release = threading.Event()

    class App:
        def deploy(self, **_kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            release.wait(2)
            with lock:
                active -= 1
            return self

        def get_tags(self, **_kwargs):
            return {}

        def set_tags(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "modal_gen.deployments.importlib.import_module",
        lambda _name: SimpleNamespace(app=App()),
    )
    jobs = [service.start_deploy("modal-2d", app_name=target.app_name) for target in targets]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with lock:
            if active == 2:
                break
        time.sleep(0.01)
    with lock:
        assert active == 2
        assert peak == 2
    release.set()
    for job in jobs:
        assert _wait(service, str(job["id"]))["status"] == "succeeded"
    assert peak == 2
