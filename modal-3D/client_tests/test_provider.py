from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from modal_3d.client import artifacts
from modal_3d.client.provider import Modal3DProvider


class Resolver:
    def __init__(self, data: bytes, path: Path) -> None:
        self.data = data
        self.path = path
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.resolve_calls = 0

    def describe_input(self, artifact_id: str, *, owner_client: str, owner_origin: str):
        return SimpleNamespace(
            id=artifact_id,
            role="primary-image",
            mime="image/png",
            bytes=len(self.data),
            hash=f"sha256:{self.sha256}",
        )

    def resolve_input(self, artifact_id: str, *, owner_client: str, owner_origin: str):
        self.resolve_calls += 1
        return SimpleNamespace(
            id=artifact_id,
            role="primary-image",
            mime="image/png",
            bytes=len(self.data),
            hash=f"sha256:{self.sha256}",
            path=self.path,
        )


class RemoteJobs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def submit_remote_source(self, source_path: str, *, source_sha256: str, **kwargs):
        self.calls.append((source_path, source_sha256))
        return {
            "id": "provider_job_01",
            "status": "running",
            "model": kwargs["model"],
            "result": None,
            "error_code": None,
            "retryable": True,
        }


def request(resolver: Resolver):
    source = {
        "id": "artifact_image_01",
        "role": "primary-image",
        "mime": "image/png",
        "hash": f"sha256:{resolver.sha256}",
    }
    context = SimpleNamespace(
        artifacts=resolver,
        owner_client="agentscape",
        owner_origin="http://localhost",
        request_id="idem_remote_artifact",
    )
    return source, context


def test_provider_uses_shared_source_without_local_materialization(
    tmp_path, monkeypatch, source_png
):
    path = tmp_path / "source.png"
    path.write_bytes(source_png)
    resolver = Resolver(source_png, path)
    jobs = RemoteJobs()
    provider = Modal3DProvider(jobs)
    source, context = request(resolver)

    monkeypatch.setattr(artifacts, "remote_source_exists", lambda sha256: True)
    monkeypatch.setattr(
        artifacts,
        "upload_remote_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected upload")),
    )

    result = provider.submit(
        operation="modal-3d.asset.image_to_3d.v1",
        inputs={"sourceArtifact": source, "model": "fastsam3d-plus-plus"},
        profile="recommended",
        options={},
        context=context,
    )

    assert result["status"] == "running"
    assert resolver.resolve_calls == 0
    assert jobs.calls == [(artifacts.source_remote_path(resolver.sha256), resolver.sha256)]


def test_provider_materializes_and_uploads_only_when_shared_source_is_missing(
    tmp_path, monkeypatch, source_png
):
    path = tmp_path / "source.png"
    path.write_bytes(source_png)
    resolver = Resolver(source_png, path)
    jobs = RemoteJobs()
    provider = Modal3DProvider(jobs)
    source, context = request(resolver)
    uploads: list[tuple[bytes, str]] = []

    monkeypatch.setattr(artifacts, "remote_source_exists", lambda sha256: False)

    def upload(data: bytes, *, expected_sha256: str | None = None):
        uploads.append((data, str(expected_sha256)))
        return {"path": artifacts.source_remote_path(resolver.sha256), "sha256": resolver.sha256}

    monkeypatch.setattr(artifacts, "upload_remote_source", upload)

    result = provider.submit(
        operation="modal-3d.asset.image_to_3d.v1",
        inputs={"sourceArtifact": source, "model": "fastsam3d-plus-plus"},
        profile="recommended",
        options={},
        context=context,
    )

    assert result["status"] == "running"
    assert resolver.resolve_calls == 1
    assert uploads == [(source_png, resolver.sha256)]
    assert jobs.calls == [(artifacts.source_remote_path(resolver.sha256), resolver.sha256)]


def test_multiview_optional_images_work_through_connector(tmp_path, source_png):
    from types import SimpleNamespace

    class Operations:
        def __init__(self):
            self.refs = None
            self.uploaded = 0

        def asset(self, artifact_id):
            raise KeyError(artifact_id)

        def upload(self, data, **kwargs):
            self.uploaded += 1
            return {"id": "art_" + hashlib.sha256(data).hexdigest()}

        def submit(self, name, refs, options, job_id):
            self.refs = refs
            return {
                "id": job_id,
                "status": "queued",
                "model": name,
                "result": None,
                "error_code": None,
                "retryable": False,
            }

    source_path = tmp_path / "front.png"
    source_path.write_bytes(source_png)
    resolver = Resolver(source_png, source_path)
    source, context = request(resolver)
    ops = Operations()
    provider = Modal3DProvider(SimpleNamespace(operations=ops))
    result = provider.submit(
        operation="modal-3d.asset.multiview_to_3d.v1",
        inputs={"front": source},
        profile="recommended",
        options={},
        context=context,
    )
    assert result["status"] == "queued"
    assert list(ops.refs) == ["front"]
    assert ops.uploaded == 1


def test_provider_job_id_is_scoped_by_owner_and_origin():
    from types import SimpleNamespace

    from modal_3d.client.provider import _provider_job_id

    one = SimpleNamespace(request_id="same", owner_client="alpha", owner_origin="https://a")
    two = SimpleNamespace(request_id="same", owner_client="beta", owner_origin="https://b")
    assert _provider_job_id(one, "op") == _provider_job_id(one, "op")
    assert _provider_job_id(one, "op") != _provider_job_id(two, "op")
    assert _provider_job_id(one, "op") != _provider_job_id(one, "3d")


def test_operation_descriptor_survives_no_generation_models(monkeypatch):
    from types import SimpleNamespace

    from modal_3d.client import provider as provider_module

    monkeypatch.setattr(
        provider_module.capabilities,
        "capabilities_document",
        lambda: {"contract": "modal-3d.capabilities.v3", "models": []},
    )
    provider = Modal3DProvider(SimpleNamespace())
    doc = provider.descriptor()
    assert doc["status"] == "available"
    assert doc["capabilities"][0]["status"] == "disabled"
    assert any(cap["operation"] == "modal-3d.asset.segment_parts.v1" for cap in doc["capabilities"])
