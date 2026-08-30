from __future__ import annotations

from types import SimpleNamespace

import pytest
from modal.exception import NotFoundError

from modal_gen.deployments import DeploymentService, DeploymentTarget
from modal_gen.errors import ConnectorError


def test_deploy_requires_in_memory_credentials():
    service = DeploymentService()
    with pytest.raises(ConnectorError) as exc:
        service.deploy("modal-2d")
    assert exc.value.code == "DEPLOYMENT_CREDENTIALS_REQUIRED"


def test_status_only_marks_not_found_as_missing(monkeypatch):
    target = DeploymentTarget("modal-2d", "missing-app", "unused")

    def missing(*_args, **_kwargs):
        raise NotFoundError("missing")

    monkeypatch.setattr("modal_gen.deployments.modal.App.lookup", missing)
    row = DeploymentService._target_status(target, SimpleNamespace())
    assert row["status"] == "missing"


def test_deploy_uses_runtime_app_definition(monkeypatch):
    service = DeploymentService()
    service._client = SimpleNamespace()
    target = DeploymentTarget("modal-2d", "test-app", "runtime.module")
    calls = []

    class FakeApp:
        def deploy(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(service, "_targets", lambda _provider=None: (target,))
    monkeypatch.setattr(service, "_ensure_source_paths", lambda: None)
    monkeypatch.setattr(
        "modal_gen.deployments.importlib.import_module",
        lambda _name: SimpleNamespace(app=FakeApp()),
    )

    result = service.deploy("modal-2d")
    assert result["providers"][0]["status"] == "deployed"
    assert calls[0]["name"] == "test-app"
    assert calls[0]["strategy"] == "rolling"


def test_deploy_can_target_one_runtime_app(monkeypatch):
    service = DeploymentService()
    service._client = SimpleNamespace()
    targets = (
        DeploymentTarget("modal-3d", "app-a", "runtime.a"),
        DeploymentTarget("modal-3d", "app-b", "runtime.b"),
    )
    imported = []

    class FakeApp:
        def __init__(self, name):
            self.name = name

        def deploy(self, **_kwargs):
            imported.append(self.name)

    monkeypatch.setattr(service, "_targets", lambda _provider=None: targets)
    monkeypatch.setattr(service, "_ensure_source_paths", lambda: None)
    monkeypatch.setattr(
        "modal_gen.deployments.importlib.import_module",
        lambda name: SimpleNamespace(app=FakeApp(name)),
    )

    result = service.deploy("modal-3d", app_name="app-b")
    assert imported == ["runtime.b"]
    assert result["providers"][0]["apps"][0]["app"] == "app-b"


def test_deploy_rejects_unknown_runtime_app(monkeypatch):
    service = DeploymentService()
    service._client = SimpleNamespace()
    monkeypatch.setattr(
        service,
        "_targets",
        lambda _provider=None: (DeploymentTarget("modal-2d", "known", "runtime.known"),),
    )
    with pytest.raises(ConnectorError) as exc:
        service.deploy("modal-2d", app_name="missing")
    assert exc.value.code == "DEPLOYMENT_APP_UNKNOWN"
