from __future__ import annotations

import math
import os
from urllib.parse import urlsplit

import httpx

from ..constants import (
    MODAL_3D_OPERATION,
    MODAL_3D_OUTPUT_ROLE,
    MODAL_3D_PROVIDER,
    MODAL_3D_SOURCE_ROLE,
)
from ..errors import ProviderError
from .base import ProviderArtifact, ProviderContext, ProviderJob
from .modal3d_discovery import AgentConnection, AgentDiscovery, WindowsCredentialDiscovery

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
_CONTROL_TIMEOUT = httpx.Timeout(connect=2.0, read=20.0, write=20.0, pool=2.0)
_PREPROCESS_TIMEOUT = httpx.Timeout(connect=2.0, read=180.0, write=30.0, pool=2.0)
_ARTIFACT_TIMEOUT = httpx.Timeout(connect=2.0, read=180.0, write=20.0, pool=2.0)
_MAX_SOURCE_BYTES = 20 * 1024 * 1024
_PROVIDER_STATUSES = {
    "running",
    "succeeded",
    "failed",
    "cancel_requested",
    "connection_required",
    "cancelled",
    "expired",
}


class Modal3DAdapter:
    id = MODAL_3D_PROVIDER

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        discovery: AgentDiscovery | None = None,
    ) -> None:
        configured = endpoint if endpoint is not None else os.environ.get("MODAL_3D_AGENT_ENDPOINT")
        self._configured_endpoint = _normalize_loopback_endpoint(configured) if configured else None
        self._configured_token = (
            token if token is not None else os.environ.get("MODAL_3D_AGENT_TOKEN")
        )
        self.client = client or httpx.Client(timeout=_CONTROL_TIMEOUT, follow_redirects=False)
        self.discovery = discovery or WindowsCredentialDiscovery()

    def descriptor(self) -> dict[str, object]:
        connection = self._connection()
        capability = self._json("GET", "/v1/capabilities", connection=connection)
        _preprocess_capability(capability.get("preprocessing"))
        models = self._json_list("GET", "/v1/models", connection=connection)
        enabled: list[dict[str, object]] = []
        profile_sets: list[set[str]] = []
        for index, model in enumerate(models):
            item = _model(model, index)
            if item["status"] != "enabled":
                continue
            enabled.append(item)
            profile_sets.append(set(item["profile_ids"]))
        if not enabled:
            raise ProviderError("PROVIDER_CAPABILITY_UNAVAILABLE", "modal-3D 没有可用模型", 503)
        common_profiles = set.intersection(*profile_sets) if profile_sets else set()
        if not common_profiles:
            raise ProviderError(
                "PROVIDER_CAPABILITY_INVALID",
                "modal-3D 可用模型没有共同 profile",
                502,
            )
        health = "healthy" if len(enabled) == len(models) else "degraded"
        return self._descriptor(
            model_ids=[str(item["id"]) for item in enabled],
            profiles=sorted(common_profiles),
            health=health,
            status="available",
        )

    def unavailable_descriptor(self) -> dict[str, object]:
        return self._descriptor(model_ids=[], profiles=[], health="unavailable", status="disabled")

    def submit(
        self,
        *,
        operation: str,
        inputs: dict[str, object],
        profile: str | None,
        options: dict[str, object],
        context: ProviderContext,
    ) -> ProviderJob:
        if operation != MODAL_3D_OPERATION:
            raise ProviderError(
                "PROVIDER_OPERATION_UNSUPPORTED", f"不支持 operation: {operation}", 422
            )
        if options:
            raise ProviderError("PROVIDER_OPTIONS_UNSUPPORTED", "modal-3D 当前不接受 options", 422)
        source, model, seed = _request_inputs(inputs)
        effective_profile = profile or "recommended"
        artifact = context.artifacts.resolve_input(
            str(source["id"]),
            owner_client=context.owner_client,
            owner_origin=context.owner_origin,
        )
        _match_source(source, artifact)
        if artifact.bytes > _MAX_SOURCE_BYTES:
            raise ProviderError("PROVIDER_SOURCE_TOO_LARGE", "modal-3D source 超过 20 MiB", 422)

        connection = self._connection()
        project_id: str | None = None
        remote_submitted = False
        try:
            with artifact.path.open("rb") as stream:
                project = self._json(
                    "POST",
                    "/v1/projects",
                    files={"file": ("source.png", stream, artifact.mime)},
                    connection=connection,
                )
            project_id = _safe_opaque_id(project.get("id"), "PROVIDER_PROJECT_INVALID")
            preprocessed = self._json(
                "POST",
                f"/v1/projects/{project_id}/preprocess",
                timeout=_PREPROCESS_TIMEOUT,
                connection=connection,
            )
            _canonical(preprocessed.get("canonical"))
            generation = self._json(
                "POST",
                f"/v1/projects/{project_id}/generation",
                json={"model": model, "profile": effective_profile, "seed": seed},
                timeout=_PREPROCESS_TIMEOUT,
                connection=connection,
            )
            job_payload = generation.get("job")
            if not isinstance(job_payload, dict):
                raise ProviderError("PROVIDER_JOB_INVALID", "modal-3D generation 缺少 Job", 502)
            job = self._job(job_payload, state={"projectId": project_id})
            remote_submitted = True
            return job
        except Exception:
            if project_id and not remote_submitted:
                self._delete_project_best_effort(project_id, connection=connection)
            raise

    def get(
        self,
        provider_job_id: str,
        *,
        state: dict[str, object] | None = None,
    ) -> ProviderJob:
        connection = self._connection()
        return self._job(
            self._json(
                "GET",
                f"/v1/jobs/{_safe_opaque_id(provider_job_id, 'PROVIDER_JOB_ID_INVALID')}",
                connection=connection,
            ),
            state=state,
        )

    def cancel(
        self,
        provider_job_id: str,
        *,
        state: dict[str, object] | None = None,
    ) -> ProviderJob:
        connection = self._connection()
        return self._job(
            self._json(
                "DELETE",
                f"/v1/jobs/{_safe_opaque_id(provider_job_id, 'PROVIDER_JOB_ID_INVALID')}",
                connection=connection,
            ),
            state=state,
        )

    def iter_artifact(
        self,
        provider_job_id: str,
        artifact: ProviderArtifact,
        *,
        state: dict[str, object] | None = None,
    ):
        if artifact.role != MODAL_3D_OUTPUT_ROLE or artifact.mime != "model/gltf-binary":
            raise ProviderError("PROVIDER_ARTIFACT_INVALID", "modal-3D Artifact contract 无效", 502)
        connection = self._connection()
        headers = self._headers(connection, {"Accept": artifact.mime})
        endpoint = connection.endpoint
        try:
            with self.client.stream(
                "GET",
                (
                    f"{endpoint}/v1/jobs/"
                    f"{_safe_opaque_id(provider_job_id, 'PROVIDER_JOB_ID_INVALID')}/artifact"
                ),
                headers=headers,
                timeout=_ARTIFACT_TIMEOUT,
            ) as response:
                self._ensure_success(response)
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if content_type != artifact.mime:
                    raise ProviderError(
                        "PROVIDER_ARTIFACT_INVALID", "modal-3D Artifact MIME 不匹配", 502
                    )
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        length = int(content_length)
                    except ValueError as exc:
                        raise ProviderError(
                            "PROVIDER_ARTIFACT_INVALID", "modal-3D Content-Length 无效", 502
                        ) from exc
                    if length != artifact.bytes:
                        raise ProviderError(
                            "PROVIDER_ARTIFACT_INVALID",
                            "modal-3D Content-Length 与 descriptor 不匹配",
                            502,
                        )
                yield from response.iter_bytes()
        except httpx.RequestError as exc:
            raise ProviderError(
                "PROVIDER_CONNECTION_REQUIRED", "modal-3D Agent Artifact 读取失败", 503
            ) from exc

    def _descriptor(
        self,
        *,
        model_ids: list[str],
        profiles: list[str],
        health: str,
        status: str,
    ) -> dict[str, object]:
        return {
            "id": self.id,
            "displayName": "Modal 3D",
            "version": "1",
            "implementationRevision": "modal-3d.capabilities.v2",
            "health": health,
            "status": status,
            "contractVersion": "1",
            "artifactTransport": "connector-artifact",
            "capabilities": [
                {
                    "operation": MODAL_3D_OPERATION,
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
                                        "role": {"const": MODAL_3D_SOURCE_ROLE},
                                        "mime": {"const": "image/png"},
                                        "hash": {
                                            "type": "string",
                                            "pattern": "^sha256:[0-9a-f]{64}$",
                                        },
                                    },
                                },
                                "model": {"type": "string", "enum": model_ids},
                                "seed": {"type": "integer", "default": 42},
                            },
                        },
                        "limits": {"maxSourceBytes": _MAX_SOURCE_BYTES},
                    },
                    "output": {
                        "roles": [MODAL_3D_OUTPUT_ROLE],
                        "required": [MODAL_3D_OUTPUT_ROLE],
                        "optional": [],
                    },
                    "profiles": {profile: {} for profile in profiles},
                    "optionsSchema": {"type": "object", "additionalProperties": False},
                    "execution": {
                        "async": True,
                        "stages": ["source", "preprocess", "generation", "artifact"],
                        "durationClass": "long",
                        "costClass": "gpu",
                    },
                    "prerequisites": {"authMode": "connector-session", "connection": True},
                    "support": {"cancel": True, "resume": True, "idempotency": True},
                    "artifactTransport": "connector-artifact",
                }
            ],
        }

    def _job(
        self,
        payload: dict[str, object],
        *,
        state: dict[str, object] | None = None,
    ) -> ProviderJob:
        job_id = _safe_opaque_id(payload.get("id"), "PROVIDER_JOB_INVALID")
        status = str(payload.get("status") or "").strip()
        if status not in _PROVIDER_STATUSES:
            raise ProviderError("PROVIDER_JOB_INVALID", "modal-3D Job status 无效", 502)
        model = str(payload.get("model") or "").strip() or None
        artifact = None
        result = payload.get("result")
        if status == "succeeded":
            if not isinstance(result, dict) or not isinstance(result.get("artifact"), dict):
                raise ProviderError("PROVIDER_JOB_INVALID", "modal-3D 成功 Job 缺少 Artifact", 502)
            artifact = _artifact(result["artifact"])
        error_code = payload.get("error_code")
        retryable = payload.get("retryable")
        return ProviderJob(
            id=job_id,
            status=status,
            model=model,
            artifact=artifact,
            error_code=str(error_code).strip() if error_code else None,
            retryable=bool(retryable) if retryable is not None else None,
            state=state,
        )

    def _json(self, method: str, path: str, **kwargs) -> dict[str, object]:
        response = self._request(method, path, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("PROVIDER_RESPONSE_INVALID", "modal-3D 返回无效 JSON", 502) from exc
        if not isinstance(payload, dict):
            raise ProviderError("PROVIDER_RESPONSE_INVALID", "modal-3D 返回结构无效", 502)
        return payload

    def _json_list(self, method: str, path: str, **kwargs) -> list[object]:
        response = self._request(method, path, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("PROVIDER_RESPONSE_INVALID", "modal-3D 返回无效 JSON", 502) from exc
        if not isinstance(payload, list):
            raise ProviderError("PROVIDER_RESPONSE_INVALID", "modal-3D 返回结构无效", 502)
        return payload

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        connection = kwargs.pop("connection", None) or self._connection()
        headers = self._headers(connection, kwargs.pop("headers", {}))
        try:
            response = self.client.request(
                method,
                f"{connection.endpoint}{path}",
                headers=headers,
                timeout=kwargs.pop("timeout", _CONTROL_TIMEOUT),
                **kwargs,
            )
        except httpx.RequestError as exc:
            raise ProviderError(
                "PROVIDER_CONNECTION_REQUIRED", "modal-3D Agent 不可达", 503
            ) from exc
        self._ensure_success(response)
        return response

    @staticmethod
    def _headers(
        connection: AgentConnection, headers: dict[str, str] | None = None
    ) -> dict[str, str]:
        result = dict(headers or {})
        if connection.token:
            result["X-Modal-3D-Session"] = connection.token
        return result

    def _connection(self) -> AgentConnection:
        if self._configured_endpoint:
            return AgentConnection(
                endpoint=self._configured_endpoint,
                token=self._configured_token or "",
                agent_pid=0,
                desktop_pid=0,
            )
        try:
            discovered = self.discovery.discover()
        except (OSError, ValueError) as exc:
            raise ProviderError(
                "PROVIDER_CONNECTION_REQUIRED", "modal-3D Agent 自动发现失败", 503
            ) from exc
        if discovered is None:
            raise ProviderError(
                "PROVIDER_CONNECTION_REQUIRED", "modal-3D Agent 未运行或无法自动发现", 503
            )
        return AgentConnection(
            endpoint=_normalize_loopback_endpoint(discovered.endpoint),
            token=discovered.token,
            agent_pid=discovered.agent_pid,
            desktop_pid=discovered.desktop_pid,
        )

    @staticmethod
    def _ensure_success(response: httpx.Response) -> None:
        if 200 <= response.status_code < 300:
            return
        if response.status_code in {401, 403, 409, 503, 504}:
            raise ProviderError("PROVIDER_CONNECTION_REQUIRED", "modal-3D Agent 当前不可用", 503)
        if response.status_code in {400, 422}:
            raise ProviderError("PROVIDER_REQUEST_REJECTED", "modal-3D 拒绝请求", 422)
        if response.status_code == 410:
            raise ProviderError("PROVIDER_OUTPUT_EXPIRED", "modal-3D 产物已过期", 410)
        raise ProviderError("PROVIDER_REQUEST_FAILED", f"modal-3D HTTP {response.status_code}", 502)

    def _delete_project_best_effort(self, project_id: str, *, connection: AgentConnection) -> None:
        try:
            self._request("DELETE", f"/v1/projects/{project_id}", connection=connection)
        except ProviderError:
            pass


def _preprocess_capability(value: object) -> None:
    if not isinstance(value, dict):
        raise ProviderError(
            "PROVIDER_CAPABILITY_INVALID", "modal-3D preprocessing capability 无效", 502
        )
    download = value.get("download")
    valid = (
        value.get("kind") == "rembg"
        and value.get("local_only") is True
        and value.get("canonical_size") == 1024
        and value.get("model_downloaded") is True
        and isinstance(download, dict)
        and download.get("status") == "ready"
        and download.get("integrity") == "verified"
    )
    if not valid:
        raise ProviderError(
            "PROVIDER_PREREQUISITE_REQUIRED",
            "modal-3D 本地 preprocess 模型尚未 ready/verified",
            503,
        )


def _request_inputs(value: dict[str, object]) -> tuple[dict[str, object], str, int]:
    allowed = {"sourceArtifact", "model", "seed"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProviderError(
            "PROVIDER_REQUEST_INVALID",
            f"modal-3D inputs 包含未知字段: {', '.join(unknown)}",
            422,
        )
    source = value.get("sourceArtifact")
    if not isinstance(source, dict):
        raise ProviderError("PROVIDER_SOURCE_INVALID", "modal-3D sourceArtifact 必须是对象", 422)
    required = {"id", "role", "mime", "hash"}
    if set(source) != required:
        raise ProviderError("PROVIDER_SOURCE_INVALID", "modal-3D sourceArtifact 字段不完整", 422)
    artifact_id = _safe_opaque_id(source.get("id"), "PROVIDER_SOURCE_INVALID")
    role = str(source.get("role") or "").strip()
    mime = str(source.get("mime") or "").strip().lower()
    digest = str(source.get("hash") or "").strip().lower()
    if role != MODAL_3D_SOURCE_ROLE or mime != "image/png":
        raise ProviderError("PROVIDER_SOURCE_INVALID", "modal-3D 仅接受 primary-image PNG", 422)
    if not _sha256_hash(digest):
        raise ProviderError("PROVIDER_SOURCE_INVALID", "modal-3D sourceArtifact hash 无效", 422)
    model = _safe_model_id(value.get("model"), "PROVIDER_MODEL_INVALID", status=422)
    seed = value.get("seed", 42)
    if not isinstance(seed, int) or isinstance(seed, bool) or abs(seed) > 2**53 - 1:
        raise ProviderError("PROVIDER_SEED_INVALID", "modal-3D seed 必须是 JS 安全整数", 422)
    return {"id": artifact_id, "role": role, "mime": mime, "hash": digest}, model, seed


def _match_source(source: dict[str, object], artifact) -> None:
    if (
        artifact.id != source["id"]
        or artifact.role != source["role"]
        or artifact.mime != source["mime"]
        or artifact.hash != source["hash"]
    ):
        raise ProviderError(
            "PROVIDER_SOURCE_MISMATCH", "Connector Artifact 与 3D source 引用不一致", 409
        )
    if not artifact.path.is_file():
        raise ProviderError(
            "PROVIDER_SOURCE_MISSING", "Connector source Artifact 本地缓存不存在", 500
        )


def _canonical(value: object) -> None:
    if not isinstance(value, dict):
        raise ProviderError(
            "PROVIDER_PREPROCESS_INVALID", "modal-3D preprocess 缺少 canonical", 502
        )
    digest = str(value.get("sha256") or "").strip().lower()
    size = value.get("bytes")
    if (
        value.get("role") != "canonical-rgba"
        or value.get("mime") != "image/png"
        or value.get("width") != 1024
        or value.get("height") != 1024
        or value.get("mode") != "RGBA"
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ProviderError("PROVIDER_PREPROCESS_INVALID", "modal-3D canonical contract 无效", 502)


def _artifact(value: dict[str, object]) -> ProviderArtifact:
    artifact_id = _safe_opaque_id(value.get("id"), "PROVIDER_ARTIFACT_INVALID")
    role = str(value.get("role") or "").strip()
    mime = str(value.get("mime") or "").strip().lower()
    size = value.get("bytes")
    digest = str(value.get("sha256") or "").strip().lower()
    if role != MODAL_3D_OUTPUT_ROLE or mime != "model/gltf-binary":
        raise ProviderError("PROVIDER_ARTIFACT_INVALID", "modal-3D Artifact role/mime 无效", 502)
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0 or size > 2**53 - 1:
        raise ProviderError("PROVIDER_ARTIFACT_INVALID", "modal-3D Artifact bytes 无效", 502)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ProviderError("PROVIDER_ARTIFACT_INVALID", "modal-3D Artifact sha256 无效", 502)
    return ProviderArtifact(
        id=artifact_id,
        role=role,
        mime=mime,
        bytes=size,
        sha256=digest,
    )


def _model(value: object, index: int) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ProviderError("PROVIDER_CAPABILITY_INVALID", f"modal-3D model[{index}] 无效", 502)
    model_id = _safe_model_id(value.get("id"), "PROVIDER_CAPABILITY_INVALID", status=502)
    status = str(value.get("status") or "").strip()
    output = str(value.get("output") or "").strip()
    profiles = value.get("profiles")
    warm = value.get("warm_seconds")
    if status not in {"enabled", "degraded", "disabled"} or output not in {"geometry", "textured"}:
        raise ProviderError(
            "PROVIDER_CAPABILITY_INVALID", f"modal-3D model {model_id} 状态无效", 502
        )
    if (
        not isinstance(warm, (int, float))
        or isinstance(warm, bool)
        or not math.isfinite(float(warm))
    ):
        raise ProviderError(
            "PROVIDER_CAPABILITY_INVALID", f"modal-3D model {model_id} warm_seconds 无效", 502
        )
    if not isinstance(profiles, list) or not profiles:
        raise ProviderError(
            "PROVIDER_CAPABILITY_INVALID", f"modal-3D model {model_id} profiles 无效", 502
        )
    profile_ids: list[str] = []
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ProviderError(
                "PROVIDER_CAPABILITY_INVALID", f"modal-3D model {model_id} profile 无效", 502
            )
        profile_id = str(profile.get("id") or "").strip()
        if not profile_id or profile_id in profile_ids:
            raise ProviderError(
                "PROVIDER_CAPABILITY_INVALID", f"modal-3D model {model_id} profile id 无效", 502
            )
        profile_ids.append(profile_id)
    return {"id": model_id, "status": status, "output": output, "profile_ids": profile_ids}


def _safe_opaque_id(value: object, code: str) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    if not text or len(text) > 160 or any(char not in allowed for char in text):
        raise ProviderError(code, "Provider opaque ID 无效", 502)
    return text


def _safe_model_id(value: object, code: str, *, status: int) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    if not text or len(text) > 160 or any(char not in allowed for char in text):
        raise ProviderError(code, "modal-3D model ID 无效", status)
    return text


def _sha256_hash(value: str) -> bool:
    return (
        value.startswith("sha256:")
        and len(value) == 71
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _normalize_loopback_endpoint(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname not in _ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("modal-3D Agent endpoint 必须是裸 loopback http origin")
    return f"http://{parsed.netloc}"
