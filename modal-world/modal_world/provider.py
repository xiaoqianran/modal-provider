from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from pathlib import Path

import modal
from modal.exception import NotFoundError, OutputExpiredError, RemoteError
from modal.exception import TimeoutError as ModalTimeoutError

from . import modal_session
from .deployment import deployment_manifest as runtime_deployment_manifest
from .worldgen_job import resolve_worldgen_job_root

OPERATION = "modal-world.world.image_to_world.v1"
MODEL = "hyworld2"
SOURCE_ROLE = "primary-image"
OUTPUT_ROLES = ("world-mesh", "world-semantics", "world-visual")
MAX_PROMPT_CHARS = 4000
OUTPUT_VOLUME = "hyworld2-worldgen-output"


class ProviderFault(RuntimeError):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class ModalWorldProvider:
    id = "modal-world"

    def __init__(
        self,
        *,
        connected: Callable[[], bool] = modal_session.connected,
        client: Callable[[], modal.Client] = modal_session.client,
        function_lookup=modal.Function.from_name,
        call_lookup=modal.FunctionCall.from_id,
        volume_lookup=modal.Volume.from_name,
    ) -> None:
        self._connected = connected
        self._client = client
        self._function_lookup = function_lookup
        self._call_lookup = call_lookup
        self._volume_lookup = volume_lookup

    def descriptor(self) -> dict[str, object]:
        status = "available" if self._connected() else "disabled"
        health = "healthy" if self._connected() else "unavailable"
        return _descriptor(status=status, health=health)

    def unavailable_descriptor(self) -> dict[str, object]:
        return _descriptor(status="disabled", health="unavailable")

    def connection_status(self) -> dict[str, object]:
        return {"connected": self._connected(), "managed": True}

    def connect(self, token_id: str, token_secret: str) -> dict[str, object]:
        modal_session.connect(token_id, token_secret)
        return self.connection_status()

    async def connect_async(self, token_id: str, token_secret: str) -> dict[str, object]:
        await modal_session.connect_async(token_id, token_secret)
        return self.connection_status()

    def disconnect(self) -> dict[str, object]:
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
        if profile not in {None, "recommended"}:
            raise ProviderFault(
                "PROVIDER_PROFILE_UNSUPPORTED", "modal-world only supports recommended", 422
            )
        force = options.get("force", False) if options else False
        if set(options) - {"force"} or not isinstance(force, bool):
            raise ProviderFault(
                "PROVIDER_OPTIONS_UNSUPPORTED", "modal-world only accepts boolean force", 422
            )

        source = inputs.get("sourceArtifact")
        prompt = inputs.get("prompt")
        model = inputs.get("model", MODEL)
        seed = inputs.get("seed", 42)
        if not isinstance(source, dict) or not isinstance(prompt, str) or not prompt.strip():
            raise ProviderFault(
                "PROVIDER_REQUEST_INVALID", "sourceArtifact and prompt are required", 422
            )
        if (
            len(prompt.strip()) > MAX_PROMPT_CHARS
            or model != MODEL
            or not isinstance(seed, int)
            or isinstance(seed, bool)
        ):
            raise ProviderFault("PROVIDER_REQUEST_INVALID", "prompt/model/seed is invalid", 422)

        resolver = getattr(context, "artifacts", None)
        if resolver is None:
            raise ProviderFault("PROVIDER_CONTEXT_INVALID", "artifact resolver is missing", 500)
        artifact_id = str(source.get("id") or "")
        owner_client = str(getattr(context, "owner_client", ""))
        owner_origin = str(getattr(context, "owner_origin", ""))
        local = resolver.resolve_input(
            artifact_id, owner_client=owner_client, owner_origin=owner_origin
        )
        _match_source(source, local)

        job_id = _world_job_id(context)
        source_name = "reference.png"
        volume_path = _volume_path(job_id, source_name)
        client = self._client()
        volume = self._volume_lookup(OUTPUT_VOLUME, client=client)
        with volume.batch_upload(force=True) as batch:
            batch.put_file(Path(local.path), volume_path)

        function = self._function_lookup("modal-world", "worldgen_pipeline", client=client)
        call = function.spawn(
            job_id=job_id, prompt=prompt.strip(), source_name=source_name, seed=seed, force=force
        )
        return {"id": call.object_id, "status": "running", "model": MODEL, "artifacts": []}

    def get(self, provider_job_id: str) -> dict[str, object]:
        try:
            value = self._call_lookup(provider_job_id, client=self._client()).get(timeout=0)
        except (ModalTimeoutError, TimeoutError):
            return {"id": provider_job_id, "status": "running", "model": MODEL, "artifacts": []}
        except (OutputExpiredError, NotFoundError):
            return {
                "id": provider_job_id,
                "status": "expired",
                "model": MODEL,
                "artifacts": [],
                "error_code": "remote.output_expired",
                "retryable": False,
            }
        except RemoteError:
            return {
                "id": provider_job_id,
                "status": "failed",
                "model": MODEL,
                "artifacts": [],
                "error_code": "remote.execution_failed",
                "retryable": False,
            }
        return _job(provider_job_id, value)

    def cancel(self, provider_job_id: str) -> dict[str, object]:
        call = self._call_lookup(provider_job_id, client=self._client())
        try:
            call.cancel()
        except (OutputExpiredError, NotFoundError):
            return {
                "id": provider_job_id,
                "status": "expired",
                "model": MODEL,
                "artifacts": [],
                "retryable": False,
            }
        return {
            "id": provider_job_id,
            "status": "cancel_requested",
            "model": MODEL,
            "artifacts": [],
            "retryable": True,
        }

    def iter_artifact(self, provider_job_id: str, artifact_id: str) -> Iterator[bytes]:
        value = self._call_lookup(provider_job_id, client=self._client()).get(timeout=0)
        if not isinstance(value, dict):
            raise ProviderFault("PROVIDER_ARTIFACT_INVALID", "world result is invalid", 502)
        raw = value.get("artifacts")
        if not isinstance(raw, list):
            raise ProviderFault("PROVIDER_ARTIFACT_NOT_FOUND", "artifact not found", 404)
        artifact = next(
            (item for item in raw if isinstance(item, dict) and item.get("id") == artifact_id), None
        )
        if artifact is None or not isinstance(artifact.get("path"), str):
            raise ProviderFault("PROVIDER_ARTIFACT_NOT_FOUND", "artifact not found", 404)
        volume = self._volume_lookup(OUTPUT_VOLUME, client=self._client())
        yield from volume.read_file(artifact["path"])


def create_provider() -> ModalWorldProvider:
    return ModalWorldProvider()


def _descriptor(*, status: str, health: str) -> dict[str, object]:
    return {
        "id": "modal-world",
        "displayName": "Modal World",
        "version": "1",
        "implementationRevision": "modal-world.generation.v1",
        "health": health,
        "status": status,
        "contractVersion": "1",
        "artifactTransport": "connector-artifact",
        "capabilities": [
            {
                "operation": OPERATION,
                "version": "1",
                "displayName": "Image to World",
                "category": "world-generation",
                "status": status,
                "input": {
                    "types": ["image", "text"],
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["sourceArtifact", "prompt"],
                        "properties": {
                            "sourceArtifact": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["id", "role", "mime", "hash"],
                                "properties": {
                                    "id": {"type": "string", "minLength": 1},
                                    "role": {"const": SOURCE_ROLE},
                                    "mime": {"const": "image/png"},
                                    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                                },
                            },
                            "prompt": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": MAX_PROMPT_CHARS,
                            },
                            "model": {"type": "string", "enum": [MODEL], "default": MODEL},
                            "seed": {"type": "integer", "default": 42},
                        },
                    },
                },
                "output": {
                    "roles": list(OUTPUT_ROLES),
                    "required": list(OUTPUT_ROLES),
                    "optional": [],
                },
                "profiles": {"recommended": {}},
                "optionsSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"force": {"type": "boolean", "default": False}},
                },
                "execution": {"async": True, "durationClass": "long", "costClass": "gpu"},
                "prerequisites": {"authMode": "connector-session", "connection": True},
                "support": {"cancel": True, "resume": True, "idempotency": True},
                "artifactTransport": "connector-artifact",
            }
        ],
    }


def _job(provider_job_id: str, value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("model") != MODEL:
        return {
            "id": provider_job_id,
            "status": "failed",
            "model": MODEL,
            "artifacts": [],
            "error_code": "remote.invalid_response",
            "retryable": False,
        }
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return {
            "id": provider_job_id,
            "status": "failed",
            "model": MODEL,
            "artifacts": [],
            "error_code": "remote.invalid_response",
            "retryable": False,
        }
    return {
        "id": provider_job_id,
        "status": "succeeded",
        "model": MODEL,
        "artifacts": [dict(item) for item in artifacts if isinstance(item, dict)],
        "retryable": False,
    }


def _match_source(source: dict[str, object], artifact: object) -> None:
    role = str(getattr(artifact, "role", ""))
    mime = str(getattr(artifact, "mime", ""))
    digest = str(getattr(artifact, "hash", ""))
    if (
        role != SOURCE_ROLE
        or mime != "image/png"
        or source.get("role") != role
        or source.get("mime") != mime
        or source.get("hash") != digest
    ):
        raise ProviderFault(
            "PROVIDER_SOURCE_INVALID", "source artifact identity does not match", 422
        )


def _world_job_id(context: object) -> str:
    request_id = str(getattr(context, "request_id", ""))
    digest = hashlib.sha256(request_id.encode()).hexdigest()[:32]
    return f"world_{digest}"


def _volume_path(job_id: str, name: str) -> str:
    root = resolve_worldgen_job_root(job_id).relative_to("/worldgen").as_posix()
    return f"/{root}/{name}"
