"""Deployment CLI and local control API tests; never contact the Modal cloud."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from modal_gen.app import build_runtime, create_app
from modal_gen.deployment import cli
from modal_gen.deployment.service import DeploymentService, DeploymentTarget
from modal_gen.storage import Store


def adapter():
    return SimpleNamespace(
        id="modal-2d",
        deployment_manifest=lambda: {
            "provider": "modal-2d",
            "targets": [
                {"app": "worker-a", "module": "test.worker_a", "revision": "sha256-abc"},
                {"app": "worker-b", "module": "test.worker_b", "revision": "sha256-def"},
            ],
            "utilities": [{"app": "utility", "module": "test.utility"}],
        },
    )


def test_cli_dry_run_is_local_and_restricts_exact_app(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_manifest_adapters", lambda: [adapter()])
    monkeypatch.setattr(
        cli.CredentialStore, "load", lambda self: pytest.fail("Dry run reads secrets")
    )
    assert cli.main(["deploy", "--provider", "modal-2d", "--app", "worker-b", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "worker-b" in output and "worker-a" not in output
    assert cli.main(["stop", "--provider", "modal-2d", "--dry-run"]) == 0


@pytest.mark.parametrize(
    "args",
    [
        ["stop", "--yes"],
        ["stop", "--provider", "modal-2d"],
    ],
)
def test_stop_requires_explicit_scope_and_confirmation(monkeypatch, args):
    monkeypatch.setattr(cli, "load_manifest_adapters", lambda: [adapter()])
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2


def test_stop_rejects_unlisted_app(monkeypatch):
    monkeypatch.setattr(cli, "load_manifest_adapters", lambda: [adapter()])
    assert cli.main(["stop", "--app", "unrelated-app", "--yes", "--dry-run"]) == 1


def test_stop_invokes_only_whitelisted_modal_cli_and_passes_environment(monkeypatch):
    service = DeploymentService(
        targets=(DeploymentTarget("modal-2d", "worker-a", "test.worker_a"),)
    )
    service._client = object()
    service._cli_credentials = ("ak_test", "as_test")
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("modal_gen.deployment.service.subprocess.run", fake_run)
    monkeypatch.setattr("modal_gen.deployment.service._modal_executable", lambda: "modal")
    result = service.stop_apps("modal-2d", app_name="worker-a", environment_name="staging")
    assert result["providers"][0]["apps"][0]["status"] == "stopped"
    assert len(calls) == 1
    assert calls[0][0] == ["modal", "app", "stop", "worker-a", "--yes", "--env", "staging"]
    assert calls[0][1]["env"]["MODAL_TOKEN_SECRET"] == "as_test"


def test_modal_cli_resolves_relative_to_active_python(monkeypatch, tmp_path):
    from modal_gen.deployment import service as module

    executable = tmp_path / ("modal.exe" if module.os.name == "nt" else "modal")
    executable.write_bytes(b"test")
    monkeypatch.setattr(module.sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    assert module._modal_executable() == str(executable)


def test_admin_api_requires_token_and_confirmation(tmp_path):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[])
    with TestClient(create_app(runtime)) as client:
        assert client.get("/v1/deployments").status_code == 401
        headers = {"X-Modal-Gen-Session": "wangran"}
        status = client.get("/v1/deployments", headers=headers)
        assert status.status_code == 200
        assert status.json()["connected"] is False
        assert client.get("/v1/deployments/jobs", headers=headers).status_code == 200
        denied = client.post("/v1/deployments/stop", headers=headers, json={})
        assert denied.status_code == 422
        assert client.post("/v1/deployments/deploy", headers=headers, json={}).status_code == 422
        assert client.get("/v1/secrets/huggingface", headers=headers).status_code == 404
        assert client.get("/health").status_code == 200


def test_admin_api_submits_async_jobs_without_contacting_modal(tmp_path, monkeypatch):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[adapter()])
    started = []
    monkeypatch.setattr(
        runtime.deployments,
        "start_deploy",
        lambda **kw: (
            started.append(kw)
            or {
                "id": "dep_123",
                "status": "queued",
            }
        ),
    )
    monkeypatch.setattr(
        runtime.deployments,
        "start_stop",
        lambda **kw: {
            "id": "dep_stop",
            "status": "queued",
        },
    )
    monkeypatch.setattr(
        runtime.deployments,
        "deployment_job",
        lambda job_id: {
            "id": job_id,
            "status": "running",
        },
    )
    with TestClient(create_app(runtime)) as client:
        headers = {"X-Modal-Gen-Session": "wangran"}
        start = client.post(
            "/v1/deployments/deploy",
            headers=headers,
            json={"provider": "modal-2d", "app": "worker-a"},
        )
        assert start.status_code == 202
        assert start.json()["job"]["id"] == "dep_123"
        assert started == [
            {
                "provider": "modal-2d",
                "app_name": "worker-a",
                "environment_name": None,
            }
        ]
        job = client.get("/v1/deployments/jobs/dep_123", headers=headers)
        assert job.json()["status"] == "running"
        stop = client.post(
            "/v1/deployments/stop",
            headers=headers,
            json={"provider": "modal-2d", "app": "worker-a", "confirm": True},
        )
        assert stop.status_code == 202
        assert stop.json()["job"]["id"] == "dep_stop"


def test_local_ui_deployment_proxy_and_origin_guard(monkeypatch):
    from modal_gen.ui.server import Handler, LiveGateway

    fake = SimpleNamespace(
        client_address=("127.0.0.1", 50000),
        headers={
            "Host": "127.0.0.1:48124",
            "Origin": "http://127.0.0.1:48124",
        },
    )
    assert Handler._deployment_allowed(fake, write=True)
    fake.client_address = ("192.0.2.10", 50000)
    assert not Handler._deployment_allowed(fake, write=True)
    fake.client_address = ("127.0.0.1", 50000)
    fake.headers["Origin"] = "https://attacker.invalid"
    assert not Handler._deployment_allowed(fake, write=True)

    gateway = LiveGateway()
    calls = []

    def fake_req(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"job": {"id": "dep_abc"}}

    monkeypatch.setattr(gateway, "_req", fake_req)
    assert gateway.deployment_action("deploy", {"app": "worker-a"})["job"]["id"] == "dep_abc"
    assert calls[-1][0:2] == ("POST", "/v1/deployments/deploy")
    assert "X-Modal-Gen-Session" in calls[-1][2]["headers"]
    gateway.deployment_job("dep_abc")
    assert calls[-1][1] == "/v1/deployments/jobs/dep_abc"
