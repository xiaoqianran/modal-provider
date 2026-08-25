from pathlib import Path

import pytest

from modal_2d_client import artifacts
from modal_2d_client.contracts import ContractError


class RemoteFunction:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def remote(self, artifact_id):
        self.calls.append(artifact_id)
        return self.data


def test_fetch_validates_then_caches_atomically(tmp_path: Path, monkeypatch, png_artifact):
    data, descriptor = png_artifact
    remote = RemoteFunction(data)
    monkeypatch.setenv("MODAL_2D_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(artifacts, "client", lambda: object())
    monkeypatch.setattr(artifacts.modal.Function, "from_name", lambda *args, **kwargs: remote)

    path = artifacts.fetch(descriptor)
    assert path.read_bytes() == data
    assert remote.calls == ["art_abc"]
    assert not list(tmp_path.rglob("*.part"))

    assert artifacts.fetch(descriptor) == path
    assert remote.calls == ["art_abc"]


def test_fetch_rejects_tampered_remote_bytes(tmp_path: Path, monkeypatch, png_artifact):
    _, descriptor = png_artifact
    remote = RemoteFunction(b"\x89PNG\r\n\x1a\ntampered")
    monkeypatch.setenv("MODAL_2D_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(artifacts, "client", lambda: object())
    monkeypatch.setattr(artifacts.modal.Function, "from_name", lambda *args, **kwargs: remote)
    with pytest.raises(ContractError):
        artifacts.fetch(descriptor)
    assert not list(tmp_path.rglob("*.part"))
