from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from modal_3d_client import artifacts
from modal_3d_client.conditioning import BackgroundMaskRequired
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


def test_validate_source_image_accepts_png_jpeg_webp(source_png, source_jpeg, source_webp):
    cases = [
        (source_png, "image/png", ".png", [640, 480]),
        (source_jpeg, "image/jpeg", ".jpg", [320, 240]),
        (source_webp, "image/webp", ".webp", [256, 192]),
    ]
    for data, media_type, extension, dimensions in cases:
        result = artifacts.validate_source_image(data)
        assert result["bytes"] == len(data)
        assert result["digest"] == f"sha256:{hashlib.sha256(data).hexdigest()}"
        assert result["mediaType"] == media_type
        assert result["extension"] == extension
        assert [result["width"], result["height"]] == dimensions


def test_validate_source_image_does_not_require_rgba_or_1024(source_jpeg):
    result = artifacts.validate_source_image(source_jpeg)
    assert result["mode"] == "RGB"
    assert (result["width"], result["height"]) == (320, 240)


def test_validate_source_image_rejects_unsupported_format():
    image = Image.new("RGB", (64, 64), "red")
    stream = io.BytesIO()
    image.save(stream, format="BMP")
    with pytest.raises(ContractError, match="unsupported source image format"):
        artifacts.validate_source_image(stream.getvalue())


def test_validate_source_image_enforces_byte_limit(monkeypatch, source_png):
    monkeypatch.setattr(artifacts, "SOURCE_MAX_BYTES", len(source_png) - 1)
    with pytest.raises(ContractError, match="20 MiB"):
        artifacts.validate_source_image(source_png)


def test_upload_source_uploads_locally_conditioned_canonical(monkeypatch, source_jpeg, mask_png):
    volume = Volume()
    monkeypatch.setattr(artifacts, "_volume", lambda: volume)
    result = artifacts.upload_source(source_jpeg, mask=mask_png)
    canonical = volume.batch.files[result["path"]]

    assert result["path"].startswith("client-inputs/")
    assert result["path"].endswith(".png")
    # The uploaded bytes are the canonical form, never the raw source.
    assert canonical != source_jpeg
    assert result["path"] == f"client-inputs/{hashlib.sha256(canonical).hexdigest()}.png"

    with Image.open(io.BytesIO(canonical)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert image.size == (1024, 1024)
        assert image.getchannel("A").getextrema() != (255, 255)

    assert result["conditioning"]["strategy"] == "birefnet"
    assert result["conditioning"]["source_sha256"] == hashlib.sha256(source_jpeg).hexdigest()


def test_upload_source_preserves_existing_alpha_without_a_mask(monkeypatch, source_rgba):
    volume = Volume()
    monkeypatch.setattr(artifacts, "_volume", lambda: volume)
    result = artifacts.upload_source(source_rgba)
    assert result["conditioning"]["strategy"] == "preserve-alpha"
    assert volume.batch.files[result["path"]]


def test_upload_source_requires_a_mask_for_opaque_sources(monkeypatch, source_jpeg):
    monkeypatch.setattr(artifacts, "_volume", lambda: Volume())
    with pytest.raises(BackgroundMaskRequired):
        artifacts.upload_source(source_jpeg)


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


def test_cached_artifact_uses_public_descriptor_without_remote_path(
    tmp_path: Path, monkeypatch, glb_bytes
):
    sha = hashlib.sha256(glb_bytes).hexdigest()
    monkeypatch.setenv("MODAL_3D_CLIENT_DATA_DIR", str(tmp_path))
    cache = artifacts._cache_path(sha)
    cache.write_bytes(glb_bytes)
    descriptor = {
        "id": "art_cached",
        "role": "primary-glb",
        "mediaType": "model/gltf-binary",
        "digest": f"sha256:{sha}",
        "mime": "model/gltf-binary",
        "sha256": sha,
        "bytes": len(glb_bytes),
    }
    public, path = artifacts.cached(descriptor, model="fastsam3d-plus-plus")
    assert path == cache
    assert public["id"] == "art_cached"
    assert "path" not in public
