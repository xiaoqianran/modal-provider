from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import modal_gen.app as app_module
from modal_gen.credentials import CredentialStore


def test_credentials_persist_and_replace(tmp_path: Path):
    path = tmp_path / ".secrets" / "modal.json"
    store = CredentialStore(path)

    assert store.load() is None
    store.save("ak_first", "as_first")
    first = store.load()
    assert first is not None
    assert first.token_id == "ak_first"
    assert first.token_secret == "as_first"

    store.save("ak_second", "as_second")
    second = CredentialStore(path).load()
    assert second is not None
    assert second.token_id == "ak_second"
    assert second.token_secret == "as_second"
    assert "ak_first" not in path.read_text(encoding="utf-8")
    assert "as_first" not in path.read_text(encoding="utf-8")


def test_credentials_reject_empty_values(tmp_path: Path):
    store = CredentialStore(tmp_path / "modal.json")
    try:
        store.save("", "as_secret")
    except ValueError:
        pass
    else:
        raise AssertionError("empty credentials must not be persisted")


def test_app_restores_saved_credentials_and_new_login_replaces_them(monkeypatch, tmp_path: Path):
    path = tmp_path / ".secrets" / "modal.json"
    CredentialStore(path).save("ak_old", "as_old")
    monkeypatch.setenv("MODAL_GEN_CREDENTIALS_FILE", str(path))

    deployment_connects = []
    provider_connects = []

    class Deployments:
        async def connect_async(self, token_id, token_secret):
            deployment_connects.append((token_id, token_secret))

        def disconnect(self):
            return None

    class Capabilities:
        async def connect_all_async(self, token_id, token_secret):
            provider_connects.append((token_id, token_secret))
            return [{"id": "modal-2d", "connected": True}]

        def disconnect_all(self):
            return []

    fake_runtime = SimpleNamespace(deployments=Deployments(), capabilities=Capabilities())
    monkeypatch.setattr(app_module, "runtime", lambda: fake_runtime)

    with TestClient(app_module.create_app()) as client:
        assert deployment_connects == [("ak_old", "as_old")]
        assert provider_connects == [("ak_old", "as_old")]
        response = client.post(
            "/v1/providers/connect",
            json={"tokenId": "ak_new", "tokenSecret": "as_new"},
            headers={"X-Modal-Gen-Session": "wangran"},
        )
        assert response.status_code == 200

    saved = CredentialStore(path).load()
    assert saved is not None
    assert saved.token_id == "ak_new"
    assert saved.token_secret == "as_new"
    assert deployment_connects[-1] == ("ak_new", "as_new")
    assert provider_connects[-1] == ("ak_new", "as_new")
