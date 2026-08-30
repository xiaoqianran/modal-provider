from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

from . import capabilities, modal_session
from .constants import (
    ARTIFACT_ROLE,
    DEFAULT_MODEL,
    MAX_BATCH_SIZE,
    MAX_PROMPT_CHARS,
    MAX_SEED,
    OPERATION,
)
from .contracts import ContractError
from .jobs import JobService
from .modal_session import NotConnectedError


class ProviderFault(RuntimeError):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class Modal2DProvider:
    id = "modal-2d"

    def __init__(self, jobs: JobService | None = None) -> None:
        self._jobs = jobs

    @property
    def jobs(self) -> JobService:
        if self._jobs is None:
            self._jobs = JobService()
        return self._jobs

    def descriptor(self) -> dict[str, object]:
        try:
            document = capabilities.document(refresh_remote=False)
        except NotConnectedError:
            if not modal_session.connected():
                return self.unavailable_descriptor()
            try:
                document = capabilities.document(refresh_remote=True)
            except (NotConnectedError, ContractError):
                return self.unavailable_descriptor()
        except ContractError:
            return self.unavailable_descriptor()
        model_ids = [str(item["id"]) for item in document["models"]]  # type: ignore[index]
        return _descriptor(model_ids=model_ids, status="available", health="healthy")

    def unavailable_descriptor(self) -> dict[str, object]:
        return _descriptor(model_ids=[], status="disabled", health="unavailable")

    def connection_status(self) -> dict[str, object]:
        return {"connected": modal_session.connected(), "managed": True}

    def connect(self, token_id: str, token_secret: str) -> dict[str, object]:
        modal_session.connect(token_id, token_secret)
        return self.connection_status()

    def disconnect(self) -> dict[str, object]:
        modal_session.disconnect()
        return self.connection_status()

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
                "PROVIDER_OPERATION_UNSUPPORTED",
                f"unsupported operation: {operation}",
                422,
            )
        if profile not in {None, "recommended"}:
            raise ProviderFault(
                "PROVIDER_PROFILE_UNSUPPORTED", "modal-2D only supports recommended", 422
            )
        if options:
            raise ProviderFault(
                "PROVIDER_OPTIONS_UNSUPPORTED", "modal-2D does not accept options", 422
            )
        try:
            state = self.jobs.submit(inputs, job_id=_provider_job_id(context, "2d"))
        except ContractError as exc:
            raise ProviderFault("PROVIDER_REQUEST_INVALID", str(exc), 422) from exc
        return _job(state)

    def get(self, provider_job_id: str) -> dict[str, object]:
        return _job(self.jobs.poll(provider_job_id))

    def cancel(self, provider_job_id: str) -> dict[str, object]:
        return _job(self.jobs.cancel(provider_job_id))

    def iter_artifact(self, provider_job_id: str, artifact_id: str) -> Iterator[bytes]:
        state = self.jobs.poll(provider_job_id)
        artifacts = _result_artifacts(state)
        for index, artifact in enumerate(artifacts):
            if artifact.get("id") != artifact_id:
                continue
            artifact_index = index if len(artifacts) > 1 else None
            descriptor, path = self.jobs.artifact(provider_job_id, artifact_index)
            if descriptor.get("id") != artifact_id:
                raise ProviderFault("PROVIDER_ARTIFACT_INVALID", "artifact identity changed", 502)
            yield from _read(path)
            return
        raise ProviderFault("PROVIDER_ARTIFACT_NOT_FOUND", "artifact not found", 404)


def create_provider() -> Modal2DProvider:
    return Modal2DProvider()


def _descriptor(*, model_ids: list[str], status: str, health: str) -> dict[str, object]:
    return {
        "id": "modal-2d",
        "displayName": "Modal 2D",
        "version": "1",
        "implementationRevision": "modal-2d.generation.v2",
        "health": health,
        "status": status,
        "contractVersion": "1",
        "artifactTransport": "connector-artifact",
        "capabilities": [
            {
                "operation": OPERATION,
                "version": "1",
                "displayName": "Text to Image",
                "category": "image-generation",
                "status": status,
                "input": {
                    "types": ["text"],
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["prompt"],
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": MAX_PROMPT_CHARS,
                            },
                            "model": (
                                {
                                    "type": "string",
                                    "enum": model_ids,
                                    "default": DEFAULT_MODEL,
                                }
                                if DEFAULT_MODEL in model_ids
                                else {"type": "string"}
                            ),
                            "seed": {"type": "integer", "minimum": 0, "maximum": MAX_SEED},
                            "seeds": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": MAX_BATCH_SIZE,
                                "uniqueItems": True,
                                "items": {"type": "integer", "minimum": 0, "maximum": MAX_SEED},
                            },
                            "guidance": {"type": "number", "minimum": 0, "maximum": 20},
                        },
                    },
                    "limits": {"width": 1024, "height": 1024, "batch": MAX_BATCH_SIZE},
                },
                "output": {
                    "roles": [ARTIFACT_ROLE],
                    "required": [ARTIFACT_ROLE],
                    "optional": [],
                    "multiple": True,
                },
                "profiles": {"recommended": {}},
                "optionsSchema": {"type": "object", "additionalProperties": False},
                "execution": {"async": True, "durationClass": "medium", "costClass": "gpu"},
                "prerequisites": {"authMode": "connector-session", "connection": True},
                "support": {"cancel": True, "resume": True, "idempotency": True},
                "artifactTransport": "connector-artifact",
            }
        ],
    }


def _job(state: dict[str, object]) -> dict[str, object]:
    return {
        "id": state.get("id"),
        "status": state.get("status"),
        "model": state.get("model"),
        "artifacts": _result_artifacts(state) if state.get("status") == "succeeded" else [],
        "error_code": state.get("error_code"),
        "retryable": state.get("retryable"),
    }


def _result_artifacts(state: dict[str, object]) -> list[dict[str, object]]:
    result = state.get("result")
    if not isinstance(result, dict):
        return []
    if isinstance(result.get("artifacts"), list):
        return [dict(item) for item in result["artifacts"] if isinstance(item, dict)]
    if isinstance(result.get("artifact"), dict):
        return [dict(result["artifact"])]
    return []


def _provider_job_id(context: object, prefix: str) -> str:
    request_id = str(getattr(context, "request_id", ""))
    digest = hashlib.sha256(request_id.encode()).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _read(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            yield chunk
