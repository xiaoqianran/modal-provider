from __future__ import annotations

from types import SimpleNamespace

import pytest
from modal.exception import NotFoundError

from modal_gen.deployments import DeploymentService, DeploymentTarget
from modal_gen.errors import ConnectorError


def test_deploy_requires_in_memory_credentials():
    service = DeploymentService(targets=())
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
    service = DeploymentService(targets=())
    service._client = SimpleNamespace()
    target = DeploymentTarget("modal-2d", "test-app", "runtime.module")
    calls = []

    class FakeApp:
        def deploy(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(service, "_targets", lambda _provider=None: (target,))
    monkeypatch.setattr(
        "modal_gen.deployments.importlib.import_module",
        lambda _name: SimpleNamespace(app=FakeApp()),
    )

    result = service.deploy("modal-2d")
    assert result["providers"][0]["status"] == "current"
    assert calls[0]["name"] == "test-app"
    assert calls[0]["strategy"] == "rolling"


def test_deploy_can_target_one_runtime_app(monkeypatch):
    service = DeploymentService(targets=())
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
    monkeypatch.setattr(
        "modal_gen.deployments.importlib.import_module",
        lambda name: SimpleNamespace(app=FakeApp(name)),
    )

    result = service.deploy("modal-3d", app_name="app-b")
    assert imported == ["runtime.b"]
    assert result["providers"][0]["apps"][0]["app"] == "app-b"


def test_deploy_rejects_unknown_runtime_app(monkeypatch):
    service = DeploymentService(targets=())
    service._client = SimpleNamespace()
    monkeypatch.setattr(
        service,
        "_targets",
        lambda _provider=None: (DeploymentTarget("modal-2d", "known", "runtime.known"),),
    )
    with pytest.raises(ConnectorError) as exc:
        service.deploy("modal-2d", app_name="missing")
    assert exc.value.code == "DEPLOYMENT_APP_UNKNOWN"


def test_summary_preserves_error_state():
    rows = [
        {"provider": "modal-2d", "app": "a", "module": "m.a", "status": "error"},
        {"provider": "modal-2d", "app": "b", "module": "m.b", "status": "missing"},
    ]
    assert DeploymentService._summary(rows)["providers"][0]["status"] == "error"


def test_deploy_continues_after_one_runtime_failure(monkeypatch):
    service = DeploymentService(targets=())
    service._client = SimpleNamespace()
    targets = (
        DeploymentTarget("modal-2d", "bad", "runtime.bad"),
        DeploymentTarget("modal-2d", "good", "runtime.good"),
    )
    called = []

    class FakeApp:
        def __init__(self, name):
            self.name = name

        def deploy(self, **_kwargs):
            called.append(self.name)
            if self.name == "runtime.bad":
                raise RuntimeError("boom")

    monkeypatch.setattr(service, "_targets", lambda _provider=None: targets)
    monkeypatch.setattr(
        "modal_gen.deployments.importlib.import_module",
        lambda name: SimpleNamespace(app=FakeApp(name)),
    )
    result = service.deploy("modal-2d")
    assert called == ["runtime.bad", "runtime.good"]
    assert [item["status"] for item in result["providers"][0]["apps"]] == [
        "failed",
        "current",
    ]


def test_missing_only_skips_existing_runtime(monkeypatch):
    service = DeploymentService(targets=())
    service._client = SimpleNamespace()
    targets = (
        DeploymentTarget("modal-2d", "existing", "runtime.existing"),
        DeploymentTarget("modal-2d", "missing", "runtime.missing"),
    )
    called = []

    monkeypatch.setattr(service, "_targets", lambda _provider=None: targets)
    monkeypatch.setattr(
        service,
        "_target_status",
        lambda target, _client: {
            "provider": target.provider,
            "app": target.app_name,
            "module": target.module,
            "status": "missing" if target.app_name == "missing" else "current",
        },
    )

    class FakeApp:
        def deploy(self, **kwargs):
            called.append(kwargs["name"])

    monkeypatch.setattr(
        "modal_gen.deployments.importlib.import_module",
        lambda _name: SimpleNamespace(app=FakeApp()),
    )
    service.deploy("modal-2d", missing_only=True)
    assert called == ["missing"]


def test_targets_are_discovered_from_provider_manifest():
    class Adapter:
        id = "modal-x"

        def deployment_manifest(self):
            return {
                "provider": self.id,
                "targets": [
                    {"app": "app-a", "module": "runtime.a"},
                    {"app": "app-a", "module": "runtime.a"},
                    {"app": "app-b", "module": "runtime.b"},
                ],
            }

    service = DeploymentService([Adapter()])
    assert service._targets("modal-x") == (
        DeploymentTarget("modal-x", "app-a", "runtime.a"),
        DeploymentTarget("modal-x", "app-b", "runtime.b"),
    )


def test_target_status_distinguishes_current_and_stale(monkeypatch):
    class RemoteApp:
        def __init__(self, revision):
            self.revision = revision

        def get_tags(self, **_kwargs):
            return {"modal-gen-revision": self.revision}

    target = DeploymentTarget(
        "modal-2d", "worker", "runtime.worker", "sha256-expected", ("model-a",), False
    )
    monkeypatch.setattr(
        "modal_gen.deployments.modal.App.lookup",
        lambda *_args, **_kwargs: RemoteApp("sha256-expected"),
    )
    current = DeploymentService._target_status(target, SimpleNamespace())
    assert current["status"] == "current"
    assert current["deployedRevision"] == "sha256-expected"

    monkeypatch.setattr(
        "modal_gen.deployments.modal.App.lookup",
        lambda *_args, **_kwargs: RemoteApp("sha256-old"),
    )
    stale = DeploymentService._target_status(target, SimpleNamespace())
    assert stale["status"] == "stale"
    assert stale["expectedRevision"] == "sha256-expected"
    assert stale["deployedRevision"] == "sha256-old"


def test_deploy_tags_runtime_revision(monkeypatch):
    revision = "sha256-expected"
    target = DeploymentTarget("modal-2d", "worker", "runtime.worker", revision)
    service = DeploymentService(targets=(target,))
    service._client = SimpleNamespace()
    calls = []

    class DeployedApp:
        def get_tags(self, **_kwargs):
            calls.append(("get_tags", None))
            return {"keep": "yes"}

        def set_tags(self, tags, **_kwargs):
            calls.append(("set_tags", dict(tags)))

    class LocalApp:
        def deploy(self, **kwargs):
            calls.append(("deploy", dict(kwargs)))
            return DeployedApp()

    monkeypatch.setattr(
        "modal_gen.deployments.importlib.import_module",
        lambda _name: SimpleNamespace(app=LocalApp()),
    )
    result = service.deploy("modal-2d")
    assert result["providers"][0]["status"] == "current"
    deploy_call = next(value for kind, value in calls if kind == "deploy")
    assert deploy_call["tag"] == revision
    set_tags = next(value for kind, value in calls if kind == "set_tags")
    assert set_tags == {"keep": "yes", "modal-gen-revision": revision}


def test_rejects_revision_that_modal_cannot_use_as_deployment_tag():
    with pytest.raises(ConnectorError) as exc:
        DeploymentService(
            targets=(DeploymentTarget("modal-2d", "worker", "runtime.worker", "sha256:bad"),)
        )
    assert exc.value.code == "DEPLOYMENT_REVISION_INVALID"
