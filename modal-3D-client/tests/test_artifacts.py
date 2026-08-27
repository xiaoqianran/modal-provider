from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from modal_3d_client import artifacts
from modal_3d_client.contracts import ContractError


class UploadBatch:
    def __init__(self):
        self.files = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def put_file(self, source, path):
        self.files[path] = source.read()


class Volume:
    def __init__(self, chunks=()):
        self.chunks = chunks
        self.batch = UploadBatch()
        self.paths = []

    def batch_upload(self, force=True):
        assert force is True
        return self.batch

    def read_file(self, path):
        self.paths.append(path)
        return iter(self.chunks)


def test_validate_canonical_png_requires_rgba_1024(canonical_png):
    result = artifacts.validate_canonical_png(canonical_png)
    assert result["bytes"] == len(canonical_png)
    assert result["digest"] == f"sha256:{hashlib.sha256(canonical_png).hexdigest()}"

    image = Image.new("RGB", (1024, 1024), "red")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    with pytest.raises(ContractError, match="RGBA"):
        artifacts.validate_canonical_png(stream.getvalue())

    image = Image.new("RGBA", (512, 512), "red")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    with pytest.raises(ContractError, match="1024x1024"):
        artifacts.validate_canonical_png(stream.getvalue())


def test_upload_canonical_is_content_addressed(monkeypatch, canonical_png):
    volume = Volume()
    monkeypatch.setattr(artifacts, "_volume", lambda: volume)
    result = artifacts.upload_canonical(canonical_png)
    sha = hashlib.sha256(canonical_png).hexdigest()
    assert result["path"] == f"client-inputs/{sha}.png"
    assert volume.batch.files[result["path"]] == canonical_png


def test_fetch_streams_verified_glb_to_content_cache(tmp_path: Path, monkeypatch, glb_bytes):
    sha = hashlib.sha256(glb_bytes).hexdigest()
    volume = Volume([glb_bytes[:7], glb_bytes[7:]])
    monkeypatch.setattr(artifacts, "_volume", lambda: volume)
    monkeypatch.setenv("MODAL_3D_CLIENT_DATA_DIR", str(tmp_path))
    descriptor = {
        "id": "art_remote",
        "role": "primary-glb",
        "mediaType": "model/gltf-binary",
        "digest": f"sha256:{sha}",
        "mime": "model/gltf-binary",
        "sha256": sha,
        "bytes": len(glb_bytes),
        "path": "generated/result.glb",
        "producer": {
            "provider": "modal-3d",
            "operation": "modal-3d.asset.image_to_3d.v1",
            "model": "fastsam3d-plus-plus",
        },
    }
    public, path = artifacts.fetch(descriptor, model="fastsam3d-plus-plus")
    assert path.read_bytes() == glb_bytes
    assert public["id"] == "art_remote"
    assert public["digest"] == f"sha256:{sha}"
    assert "path" not in public
    assert volume.paths == ["generated/result.glb"]
    assert not list(tmp_path.rglob("*.part"))


def test_fetch_rejects_corrupt_glb(tmp_path: Path, monkeypatch, glb_bytes):
    sha = hashlib.sha256(glb_bytes).hexdigest()
    monkeypatch.setenv("MODAL_3D_CLIENT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(artifacts, "_volume", lambda: Volume([b"not-a-glb"]))
    descriptor = {
        "role": "primary-glb",
        "mime": "model/gltf-binary",
        "sha256": sha,
        "bytes": len(glb_bytes),
        "path": "generated/result.glb",
    }
    with pytest.raises(ContractError):
        artifacts.fetch(descriptor, model="fastsam3d-plus-plus")
    assert not list(tmp_path.rglob("*.part"))
