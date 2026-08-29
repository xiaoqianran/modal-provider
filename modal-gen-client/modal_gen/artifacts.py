from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path

from .capabilities import CapabilityRegistry
from .errors import ConnectorError
from .paths import artifact_cache_dir
from .providers.protocol import ConnectorArtifactInput, ProviderArtifact
from .storage import Store

MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_ARTIFACT_CHUNKS = 65_536
_PREFIX_BYTES = 64
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_GLB_MAGIC = b"glTF"


class ArtifactService:
    def __init__(self, store: Store, capabilities: CapabilityRegistry) -> None:
        self.store = store
        self.capabilities = capabilities

    def register(
        self,
        *,
        job: dict[str, object],
        provider_artifact: ProviderArtifact,
    ) -> dict[str, object]:
        if provider_artifact.bytes <= 0 or provider_artifact.bytes > MAX_ARTIFACT_BYTES:
            raise ConnectorError("ARTIFACT_SIZE_INVALID", "Provider Artifact 大小超出限制", 502)
        existing = self.store.get_artifact_for_provider(
            str(job["id"]), provider_artifact.id
        )
        if existing:
            if (
                existing["provider_artifact_id"] != provider_artifact.id
                or existing["bytes"] != provider_artifact.bytes
                or existing["hash"] != f"sha256:{provider_artifact.sha256}"
            ):
                raise ConnectorError(
                    "ARTIFACT_IDENTITY_CONFLICT", "Provider Artifact identity 发生变化", 409
                )
            return existing
        row = {
            "id": f"artifact_{uuid.uuid4().hex}",
            "job_id": job["id"],
            "role": provider_artifact.role,
            "mime": provider_artifact.mime,
            "bytes": provider_artifact.bytes,
            "hash": f"sha256:{provider_artifact.sha256}",
            "provider_artifact_id": provider_artifact.id,
            "provider_job_id": job["provider_job_id"],
        }
        self.store.create_artifact(row)
        return row

    def resolve_input(
        self,
        artifact_id: str,
        *,
        owner_client: str,
        owner_origin: str,
    ) -> ConnectorArtifactInput:
        artifact, path = self.open(
            artifact_id,
            owner_client=owner_client,
            owner_origin=owner_origin,
        )
        return ConnectorArtifactInput(
            id=str(artifact["id"]),
            role=str(artifact["role"]),
            mime=str(artifact["mime"]),
            bytes=int(artifact["bytes"]),
            hash=str(artifact["hash"]),
            path=path,
        )

    def open(
        self,
        artifact_id: str,
        *,
        owner_client: str,
        owner_origin: str,
    ) -> tuple[dict[str, object], Path]:
        artifact = self.store.get_artifact(artifact_id, owner_client, owner_origin)
        if not artifact:
            raise ConnectorError("ARTIFACT_NOT_FOUND", "Artifact 不存在", 404)
        job = self.store.get_job(str(artifact["job_id"]), owner_client, owner_origin)
        if not job:
            raise ConnectorError("ARTIFACT_NOT_FOUND", "Artifact owner 不存在", 404)
        digest = str(artifact["hash"])
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ConnectorError("ARTIFACT_INVALID", "Artifact hash contract 无效", 500)
        destination = artifact_cache_dir() / digest[7:9] / digest[7:]
        if destination.is_file():
            self._validate_file(destination, artifact)
            return artifact, destination

        provider_artifact = ProviderArtifact(
            id=str(artifact["provider_artifact_id"]),
            role=str(artifact["role"]),
            mime=str(artifact["mime"]),
            bytes=int(artifact["bytes"]),
            sha256=digest[7:],
        )
        adapter = self.capabilities.adapter(str(job["provider"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".artifact-", suffix=".part", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                self._copy_verified(
                    adapter.iter_artifact(
                        str(artifact["provider_job_id"]),
                        provider_artifact,
                    ),
                    stream,
                    artifact,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return artifact, destination

    @staticmethod
    def summary(row: dict[str, object]) -> dict[str, object]:
        return {
            "id": row["id"],
            "role": row["role"],
            "mime": row["mime"],
            "bytes": row["bytes"],
            "hash": row["hash"],
        }

    @classmethod
    def _copy_verified(cls, chunks, stream, artifact: dict[str, object]) -> None:
        expected = int(artifact["bytes"])
        digest = hashlib.sha256()
        total = 0
        prefix = bytearray()
        for index, chunk in enumerate(chunks, start=1):
            if index > MAX_ARTIFACT_CHUNKS:
                raise ConnectorError("ARTIFACT_STREAM_INVALID", "Artifact chunk 数量超出限制", 502)
            if not isinstance(chunk, bytes):
                raise ConnectorError(
                    "ARTIFACT_STREAM_INVALID", "Artifact stream 必须返回 bytes", 502
                )
            if not chunk:
                continue
            total += len(chunk)
            if total > expected or total > MAX_ARTIFACT_BYTES:
                raise ConnectorError(
                    "ARTIFACT_INTEGRITY_FAILED", "Artifact bytes 超出 descriptor", 502
                )
            if len(prefix) < _PREFIX_BYTES:
                prefix.extend(chunk[: _PREFIX_BYTES - len(prefix)])
            digest.update(chunk)
            stream.write(chunk)
        cls._validate_facts(total, digest.hexdigest(), bytes(prefix), artifact)

    @classmethod
    def _validate_file(cls, path: Path, artifact: dict[str, object]) -> None:
        expected = int(artifact["bytes"])
        if path.stat().st_size != expected:
            path.unlink(missing_ok=True)
            raise ConnectorError("ARTIFACT_INTEGRITY_FAILED", "缓存 Artifact bytes 不匹配", 502)
        digest = hashlib.sha256()
        total = 0
        prefix = bytearray()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if len(prefix) < _PREFIX_BYTES:
                    prefix.extend(chunk[: _PREFIX_BYTES - len(prefix)])
                digest.update(chunk)
        try:
            cls._validate_facts(total, digest.hexdigest(), bytes(prefix), artifact)
        except ConnectorError:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate_facts(
        total: int,
        digest: str,
        prefix: bytes,
        artifact: dict[str, object],
    ) -> None:
        if total != artifact["bytes"]:
            raise ConnectorError("ARTIFACT_INTEGRITY_FAILED", "Artifact bytes 不匹配", 502)
        if f"sha256:{digest}" != artifact["hash"]:
            raise ConnectorError("ARTIFACT_INTEGRITY_FAILED", "Artifact SHA-256 不匹配", 502)
        if artifact["mime"] == "image/png" and prefix[:8] != _PNG_SIGNATURE:
            raise ConnectorError("ARTIFACT_INTEGRITY_FAILED", "Artifact PNG signature 不匹配", 502)
        if artifact["mime"] == "model/gltf-binary":
            if len(prefix) < 12 or prefix[:4] != _GLB_MAGIC:
                raise ConnectorError("ARTIFACT_INTEGRITY_FAILED", "Artifact GLB magic 不匹配", 502)
            version = int.from_bytes(prefix[4:8], "little")
            declared = int.from_bytes(prefix[8:12], "little")
            if version != 2 or declared != total:
                raise ConnectorError("ARTIFACT_INTEGRITY_FAILED", "Artifact GLB header 不匹配", 502)
