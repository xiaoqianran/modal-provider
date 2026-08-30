from pathlib import Path

import pytest

from modal_2d_client import artifacts
from modal_2d_client.contracts import ContractError


class RemoteVolume:
    def __init__(self, chunks):
        self.chunks = chunks
        self.paths = []

    def read_file(self, path):
        self.paths.append(path)
        return iter(self.chunks)


def test_fetch_reads_volume_directly_and_caches_atomically(
    tmp_path: Path, monkeypatch, png_artifact
):
    data, descriptor = png_artifact
    volume = RemoteVolume([data[:5], data[5:]])
    monkeypatch.setenv("MODAL_2D_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(artifacts, "client", lambda: object())
    monkeypatch.setattr(artifacts.modal.Volume, "from_name", lambda *args, **kwargs: volume)

    path = artifacts.fetch(descriptor)
    assert path.read_bytes() == data
    assert volume.paths == [f"sources/sha256/{descriptor['sha256'][:2]}/{descriptor['sha256']}"]
    assert not list(tmp_path.rglob("*.part"))

    assert artifacts.fetch(descriptor) == path
    assert volume.paths == [f"sources/sha256/{descriptor['sha256'][:2]}/{descriptor['sha256']}"]


def test_fetch_requires_direct_volume_path(tmp_path: Path, monkeypatch, png_artifact):
    _, descriptor = png_artifact
    descriptor = dict(descriptor)
    descriptor.pop("remote_path")
    monkeypatch.setenv("MODAL_2D_DATA_DIR", str(tmp_path))
    with pytest.raises(ContractError, match="remote_path"):
        artifacts.fetch(descriptor)


def test_fetch_rejects_corrupt_volume(tmp_path: Path, monkeypatch, png_artifact):
    _, descriptor = png_artifact
    volume = RemoteVolume([b"\x89PNG\r\n\x1a\ntampered"])
    monkeypatch.setenv("MODAL_2D_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(artifacts, "client", lambda: object())
    monkeypatch.setattr(artifacts.modal.Volume, "from_name", lambda *args, **kwargs: volume)

    with pytest.raises(ContractError):
        artifacts.fetch(descriptor)
    assert not list(tmp_path.rglob("*.part"))


def test_fetch_reads_legacy_volume_for_historical_descriptor(
    tmp_path: Path, monkeypatch, png_artifact
):
    data, descriptor = png_artifact
    descriptor = dict(descriptor, remote_path=f"generated/{descriptor['id']}.png")
    volume = RemoteVolume([data])
    volume_names = []
    monkeypatch.setenv("MODAL_2D_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(artifacts, "client", lambda: object())

    def from_name(name, **kwargs):
        volume_names.append(name)
        return volume

    monkeypatch.setattr(artifacts.modal.Volume, "from_name", from_name)
    path = artifacts.fetch(descriptor)
    assert path.read_bytes() == data
    assert volume_names == ["modal-2d-artifacts"]
    assert volume.paths == [f"generated/{descriptor['id']}.png"]
