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


class RemoteVolume:
    def __init__(self, chunks):
        self.chunks = chunks
        self.paths = []

    def read_file(self, path):
        self.paths.append(path)
        return iter(self.chunks)


def test_fetch_prefers_volume_and_caches_atomically(tmp_path: Path, monkeypatch, png_artifact):
    data, descriptor = png_artifact
    volume = RemoteVolume([data[:5], data[5:]])
    remote = RemoteFunction(data)
    monkeypatch.setenv("MODAL_2D_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(artifacts, "client", lambda: object())
    monkeypatch.setattr(artifacts.modal.Volume, "from_name", lambda *args, **kwargs: volume)
    monkeypatch.setattr(artifacts.modal.Function, "from_name", lambda *args, **kwargs: remote)

    path = artifacts.fetch(descriptor)
    assert path.read_bytes() == data
    assert volume.paths == ["generated/art_abc.png"]
    assert remote.calls == []
    assert not list(tmp_path.rglob("*.part"))

    assert artifacts.fetch(descriptor) == path
    assert volume.paths == ["generated/art_abc.png"]
    assert remote.calls == []


def test_fetch_falls_back_to_legacy_function_when_volume_is_unavailable(
    tmp_path: Path, monkeypatch, png_artifact
):
    data, descriptor = png_artifact
    remote = RemoteFunction(data)
    monkeypatch.setenv("MODAL_2D_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(artifacts, "client", lambda: object())
    monkeypatch.setattr(
        artifacts.modal.Volume,
        "from_name",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("volume unavailable")),
    )
    monkeypatch.setattr(artifacts.modal.Function, "from_name", lambda *args, **kwargs: remote)

    path = artifacts.fetch(descriptor)
    assert path.read_bytes() == data
    assert remote.calls == ["art_abc"]


def test_fetch_rejects_corrupt_volume_without_legacy_fallback(
    tmp_path: Path, monkeypatch, png_artifact
):
    _, descriptor = png_artifact
    volume = RemoteVolume([b"\x89PNG\r\n\x1a\ntampered"])
    remote = RemoteFunction(b"should-not-be-used")
    monkeypatch.setenv("MODAL_2D_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(artifacts, "client", lambda: object())
    monkeypatch.setattr(artifacts.modal.Volume, "from_name", lambda *args, **kwargs: volume)
    monkeypatch.setattr(artifacts.modal.Function, "from_name", lambda *args, **kwargs: remote)

    with pytest.raises(ContractError):
        artifacts.fetch(descriptor)
    assert remote.calls == []
    assert not list(tmp_path.rglob("*.part"))


def test_fetch_rejects_tampered_legacy_bytes(tmp_path: Path, monkeypatch, png_artifact):
    _, descriptor = png_artifact
    legacy = dict(descriptor)
    legacy.pop("remote_path")
    remote = RemoteFunction(b"\x89PNG\r\n\x1a\ntampered")
    monkeypatch.setenv("MODAL_2D_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(artifacts, "client", lambda: object())
    monkeypatch.setattr(artifacts.modal.Function, "from_name", lambda *args, **kwargs: remote)

    with pytest.raises(ContractError):
        artifacts.fetch(legacy)
    assert remote.calls == ["art_abc"]
    assert not list(tmp_path.rglob("*.part"))
