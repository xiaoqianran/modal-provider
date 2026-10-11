from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from modal_gen.app import build_runtime, create_app
from modal_gen.storage import Store

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "modal-command.py"


@pytest.fixture
def command_script(monkeypatch):
    module = runpy.run_path(str(SCRIPT))
    manifest = {
        "targets": [
            {"app": "worker-a", "module": "test.worker_a", "revision": "sha256-abc"},
            {"app": "worker-b", "module": "test.worker_b", "revision": "sha256-def"},
        ],
        "utilities": [{"app": "utility", "module": "test.utility"}],
    }
    monkeypatch.setattr(
        module["importlib"],
        "import_module",
        lambda _name: SimpleNamespace(deployment_manifest=lambda: manifest),
    )
    return module


def test_deploy_dry_run_selects_exact_app_and_environment(command_script, monkeypatch, capsys):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("Dry run must not execute cloud commands")

    monkeypatch.setattr(command_script["subprocess"], "run", unexpected)
    assert (
        command_script["main"](
            [
                "deploy",
                "--provider",
                "modal-2d",
                "--app",
                "worker-b",
                "--env",
                "staging",
                "--dry-run",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "test.worker_b" in output
    assert "--env staging" in output
    assert "--tag sha256-def" in output
    assert "worker-a" not in output
    assert "utility" not in output


@pytest.mark.parametrize(
    "args",
    [
        ["stop", "--yes"],
        ["stop", "--provider", "modal-2d"],
        ["stop", "--app", "unrelated-app", "--yes"],
    ],
)
def test_stop_requires_explicit_scope_confirmation_and_manifest_membership(
    command_script, monkeypatch, args
):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("Invalid stop must not execute cloud commands")

    monkeypatch.setattr(command_script["subprocess"], "run", unexpected)
    with pytest.raises(SystemExit) as exc:
        command_script["main"](args)
    assert exc.value.code == 2


def test_cloud_command_failure_stops_remaining_commands(command_script, monkeypatch):
    calls = []

    def failed(args, **_kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(command_script["subprocess"], "run", failed)
    assert command_script["main"](["deploy", "--provider", "modal-2d"]) == 7
    assert len(calls) == 1


def test_server_does_not_expose_cloud_management_endpoints(tmp_path):
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[])
    with TestClient(create_app(runtime)) as client:
        headers = {"X-Modal-Gen-Session": "wangran"}
        for path in ["/v1/deployments", "/v1/deployments/jobs", "/v1/secrets/huggingface"]:
            assert client.get(path, headers=headers).status_code == 404
        assert client.post("/v1/deployments/deploy", headers=headers, json={}).status_code == 404
        assert client.get("/health").status_code == 200
