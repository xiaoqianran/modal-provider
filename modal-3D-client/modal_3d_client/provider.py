from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

from modal_3d.deployment import deployment_manifest as runtime_deployment_manifest

from . import artifacts, capabilities, modal_session, models
from .constants import OPERATION, OUTPUT_ROLE, SOURCE_MAX_BYTES
from .contracts import ContractError
from .jobs import JobService

CONNECTOR_SOURCE_ROLE = "primary-image"


class ProviderFault(RuntimeError):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class Modal3DProvider:
    id = "modal-3d"

    def __init__(self, jobs: JobService | None = None) -> None:
        self._jobs = jobs
        self._jobs_injected = jobs is not None

    @property
    def jobs(self) -> JobService:
        if self._jobs is None:
            self._jobs = JobService(auto_reconcile=True)
        return self._jobs

    def descriptor(self) -> dict[str, object]:
        if self._jobs is None and not modal_session.connected():
            return self.unavailable_descriptor()
        try:
            document = capabilities.capabilities_document()
        except capabilities.CapabilityError:
            return self.unavailable_descriptor()
        enabled = [item for item in document["models"] if item.get("status") == "enabled"]  # type: ignore[index]
        if not enabled:
            return self.unavailable_descriptor()
        profiles = _common_profiles(enabled)
        return _descriptor(
            model_ids=[str(item["id"]) for item in enabled],
            profiles=profiles,
            status="available",
            health="healthy",
            revision=str(document["contract"]),
        )

    def unavailable_descriptor(self) -> dict[str, object]:
        return _descriptor(
            model_ids=[],
            profiles=[],
            status="disabled",
            health="unavailable",
            revision="modal-3d.capabilities.v3",
        )

    def connection_status(self) -> dict[str, object]:
        connected = self._jobs_injected or modal_session.connected()
        return {"connected": connected, "managed": not self._jobs_injected}

    def connect(self, token_id: str, token_secret: str) -> dict[str, object]:
        modal_session.connect(token_id, token_secret)
        if not self._jobs_injected:
            self.jobs.start_reconciler()
        return self.connection_status()

    async def connect_async(self, token_id: str, token_secret: str) -> dict[str, object]:
        await modal_session.connect_async(token_id, token_secret)
        if not self._jobs_injected:
            self.jobs.start_reconciler()
        return self.connection_status()

    def disconnect(self) -> dict[str, object]:
        if not self._jobs_injected and self._jobs is not None:
            self._jobs.stop_reconciler()
        modal_session.disconnect()
        return self.connection_status()

    def deployment_manifest(self) -> dict[str, object]:
        return runtime_deployment_manifest()

    def submit(
        self,
        *,
        operation: str,
        inputs: dict[str, object],
        profile: str | None,
        options: dict[str, object],
        context: object,
    ) -> dict[str, object]:
        if operation != OPERATION:
            raise ProviderFault(
                "PROVIDER_OPERATION_UNSUPPORTED", f"unsupported operation: {operation}", 422
            )
        if options:
            raise ProviderFault(
                "PROVIDER_OPTIONS_UNSUPPORTED", "modal-3D does not accept options", 422
            )
        source = inputs.get("sourceArtifact")
        model = inputs.get("model")
        seed = inputs.get("seed", 42)
        if not isinstance(source, dict) or not isinstance(model, str) or not model.strip():
            raise ProviderFault(
                "PROVIDER_REQUEST_INVALID", "sourceArtifact and model are required", 422
            )
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ProviderFault("PROVIDER_REQUEST_INVALID", "seed must be an integer", 422)
        resolver = getattr(context, "artifacts", None)
        if resolver is None:
            raise ProviderFault("PROVIDER_CONTEXT_INVALID", "artifact resolver is missing", 500)
        artifact_id = str(source.get("id") or "")
        owner_client = str(getattr(context, "owner_client", ""))
        owner_origin = str(getattr(context, "owner_origin", ""))
        describe = getattr(resolver, "describe_input", None)
        artifact = (
            describe(artifact_id, owner_client=owner_client, owner_origin=owner_origin)
            if callable(describe)
            else resolver.resolve_input(
                artifact_id, owner_client=owner_client, owner_origin=owner_origin
            )
        )
        _match_source(source, artifact)
        if artifact.bytes > SOURCE_MAX_BYTES:
            raise ProviderFault(
                "PROVIDER_SOURCE_TOO_LARGE", "source artifact exceeds provider limit", 422
            )
        source_sha256 = str(artifact.hash).removeprefix("sha256:")
        jobs = self.jobs
        try:
            submit_remote = getattr(jobs, "submit_remote_source", None)
            if not callable(submit_remote):
                local = resolver.resolve_input(
                    artifact_id, owner_client=owner_client, owner_origin=owner_origin
                )
                _match_source(source, local)
                state = jobs.submit(
                    local.path.read_bytes(),
                    model=model.strip(),
                    profile=profile or "recommended",
                    seed=seed,
                    job_id=_provider_job_id(context, "3d"),
                )
            else:
                if not artifacts.remote_source_exists(source_sha256):
                    local = resolver.resolve_input(
                        artifact_id, owner_client=owner_client, owner_origin=owner_origin
                    )
                    _match_source(source, local)
                    artifacts.upload_remote_source(
                        local.path.read_bytes(), expected_sha256=source_sha256
                    )
                state = submit_remote(
                    artifacts.source_remote_path(source_sha256),
                    source_sha256=source_sha256,
                    model=model.strip(),
                    profile=profile or "recommended",
                    seed=seed,
                    job_id=_provider_job_id(context, "3d"),
                )
        except (ContractError, models.CapabilityError) as exc:
            raise ProviderFault("PROVIDER_REQUEST_INVALID", str(exc), 422) from exc
        return _job(state)

    def get(self, provider_job_id: str) -> dict[str, object]:
        return _job(self.jobs.poll(provider_job_id))

    def cancel(self, provider_job_id: str) -> dict[str, object]:
        return _job(self.jobs.cancel(provider_job_id))

    def iter_artifact(self, provider_job_id: str, artifact_id: str) -> Iterator[bytes]:
        descriptor, path = self.jobs.artifact(provider_job_id)
        if descriptor.get("id") != artifact_id:
            raise ProviderFault("PROVIDER_ARTIFACT_NOT_FOUND", "artifact not found", 404)
        yield from _read(path)


def create_provider() -> Modal3DProvider:
    return Modal3DProvider()


def _descriptor(
    *,
    model_ids: list[str],
    profiles: list[str],
    status: str,
    health: str,
    revision: str,
) -> dict[str, object]:
    return {
        "id": "modal-3d",
        "displayName": "Modal 3D",
        "version": "1",
        "implementationRevision": revision,
        "health": health,
        "status": status,
        "contractVersion": "1",
        "artifactTransport": "connector-artifact",
        "capabilities": [
            {
                "operation": OPERATION,
                "version": "1",
                "displayName": "Image to 3D",
                "category": "asset-generation",
                "status": status,
                "input": {
                    "types": ["image"],
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["sourceArtifact", "model"],
                        "properties": {
                            "sourceArtifact": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["id", "role", "mime", "hash"],
                                "properties": {
                                    "id": {"type": "string", "minLength": 1},
                                    "role": {"const": CONNECTOR_SOURCE_ROLE},
                                    "mime": {"const": "image/png"},
                                    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                                },
                            },
                            "model": {"type": "string", "enum": model_ids},
                            "seed": {"type": "integer", "default": 42},
                        },
                    },
                    "limits": {"maxSourceBytes": SOURCE_MAX_BYTES},
                },
                "output": {"roles": [OUTPUT_ROLE], "required": [OUTPUT_ROLE], "optional": []},
                "profiles": {profile: {} for profile in profiles},
                "optionsSchema": {"type": "object", "additionalProperties": False},
                "execution": {"async": True, "durationClass": "long", "costClass": "gpu"},
                "prerequisites": {"authMode": "connector-session", "connection": True},
                "support": {"cancel": True, "resume": True, "idempotency": True},
                "artifactTransport": "connector-artifact",
            }
        ],
    }


def _common_profiles(models_: list[dict[str, object]]) -> list[str]:
    sets = []
    for model in models_:
        profiles = model.get("profiles")
        if not isinstance(profiles, list):
            continue
        sets.append(
            {str(item["id"]) for item in profiles if isinstance(item, dict) and item.get("id")}
        )
    return sorted(set.intersection(*sets)) if sets else []


def _job(state: dict[str, object]) -> dict[str, object]:
    result = state.get("result")
    artifact = result.get("artifact") if isinstance(result, dict) else None
    artifacts = [dict(artifact)] if isinstance(artifact, dict) else []
    return {
        "id": state.get("id"),
        "status": state.get("status"),
        "model": state.get("model"),
        "artifacts": artifacts if state.get("status") == "succeeded" else [],
        "error_code": state.get("error_code"),
        "retryable": state.get("retryable"),
    }


def _match_source(source: dict[str, object], artifact: object) -> None:
    role = str(getattr(artifact, "role", ""))
    mime = str(getattr(artifact, "mime", ""))
    digest = str(getattr(artifact, "hash", ""))
    if role != CONNECTOR_SOURCE_ROLE or mime != "image/png":
        raise ProviderFault(
            "PROVIDER_SOURCE_INVALID", "source artifact role/mime is incompatible", 422
        )
    if source.get("role") != role or source.get("mime") != mime or source.get("hash") != digest:
        raise ProviderFault(
            "PROVIDER_SOURCE_INVALID", "source artifact identity does not match", 422
        )


def _provider_job_id(context: object, prefix: str) -> str:
    request_id = str(getattr(context, "request_id", ""))
    digest = hashlib.sha256(request_id.encode()).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _read(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            yield chunk
