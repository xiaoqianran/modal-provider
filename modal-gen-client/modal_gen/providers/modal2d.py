from __future__ import annotations

import os
from urllib.parse import urlsplit

import httpx

from ..constants import MODAL_2D_OPERATION, MODAL_2D_OUTPUT_ROLE, MODAL_2D_PROVIDER
from ..errors import ProviderError
from .base import ProviderArtifact, ProviderJob

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
_PROVIDER_TIMEOUT = httpx.Timeout(connect=2.0, read=20.0, write=20.0, pool=2.0)
_ARTIFACT_TIMEOUT = httpx.Timeout(connect=2.0, read=120.0, write=20.0, pool=2.0)
_PROVIDER_STATUSES = {
    "running",
    "succeeded",
    "failed",
    "cancel_requested",
    "connection_required",
    "cancelled",
    "expired",
}


class Modal2DAdapter:
    id = MODAL_2D_PROVIDER

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = _normalize_loopback_endpoint(
            endpoint or os.environ.get("MODAL_2D_AGENT_ENDPOINT", "http://127.0.0.1:3212")
        )
        self.token = token if token is not None else os.environ.get("MODAL_2D_AGENT_TOKEN")
        self.client = client or httpx.Client(timeout=_PROVIDER_TIMEOUT, follow_redirects=False)

    def descriptor(self) -> dict[str, object]:
        payload = self._json("GET", "/v1/capabilities")
        if payload.get("contract") != "modal-2d.generation.v1":
            raise ProviderError("PROVIDER_CAPABILITY_INVALID", "modal-2D contract 不兼容", 502)
        if payload.get("provider") != self.id or payload.get("operation") != MODAL_2D_OPERATION:
            raise ProviderError(
                "PROVIDER_CAPABILITY_INVALID", "modal-2D capability identity 不兼容", 502
            )
        artifact = payload.get("artifact")
        models = payload.get("models")
        if (
            not isinstance(artifact, dict)
            or artifact.get("role") != MODAL_2D_OUTPUT_ROLE
            or artifact.get("mime") != "image/png"
            or artifact.get("lossless") is not True
            or not isinstance(models, list)
            or not models
        ):
            raise ProviderError(
                "PROVIDER_CAPABILITY_INVALID", "modal-2D artifact/model contract 不兼容", 502
            )
        model_ids = []
        for model in models:
            if not isinstance(model, dict) or model.get("steps") != 2:
                raise ProviderError(
                    "PROVIDER_CAPABILITY_INVALID", "modal-2D model contract 不兼容", 502
                )
            model_id = str(model.get("id") or "").strip()
            if not model_id:
                raise ProviderError("PROVIDER_CAPABILITY_INVALID", "modal-2D model id 缺失", 502)
            model_ids.append(model_id)
        return self._descriptor(model_ids=model_ids, health="healthy", status="available")

    def unavailable_descriptor(self) -> dict[str, object]:
        return self._descriptor(model_ids=[], health="unavailable", status="disabled")

    def submit(
        self,
        *,
        operation: str,
        inputs: dict[str, object],
        profile: str | None,
        options: dict[str, object],
    ) -> ProviderJob:
        if operation != MODAL_2D_OPERATION:
            raise ProviderError(
                "PROVIDER_OPERATION_UNSUPPORTED", f"不支持 operation: {operation}", 422
            )
        if profile not in {None, "recommended"}:
            raise ProviderError(
                "PROVIDER_PROFILE_UNSUPPORTED", "modal-2D 仅支持 recommended profile", 422
            )
        if options:
            raise ProviderError("PROVIDER_OPTIONS_UNSUPPORTED", "modal-2D 当前不接受 options", 422)
        return self._job(self._json("POST", "/v1/jobs", json=inputs))

    def get(self, provider_job_id: str) -> ProviderJob:
        return self._job(self._json("GET", f"/v1/jobs/{_safe_id(provider_job_id)}"))

    def cancel(self, provider_job_id: str) -> ProviderJob:
        return self._job(self._json("DELETE", f"/v1/jobs/{_safe_id(provider_job_id)}"))

    def iter_artifact(self, provider_job_id: str, artifact: ProviderArtifact):
        headers = self._headers({"Accept": artifact.mime})
        try:
            with self.client.stream(
                "GET",
                f"{self.endpoint}/v1/jobs/{_safe_id(provider_job_id)}/artifact",
                headers=headers,
                timeout=_ARTIFACT_TIMEOUT,
            ) as response:
                self._ensure_success(response)
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if content_type != artifact.mime:
                    raise ProviderError(
                        "PROVIDER_ARTIFACT_INVALID", "modal-2D Artifact MIME 不匹配", 502
                    )
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        length = int(content_length)
                    except ValueError as exc:
                        raise ProviderError(
                            "PROVIDER_ARTIFACT_INVALID", "modal-2D Content-Length 无效", 502
                        ) from exc
                    if length != artifact.bytes:
                        raise ProviderError(
                            "PROVIDER_ARTIFACT_INVALID",
                            "modal-2D Content-Length 与 descriptor 不匹配",
                            502,
                        )
                yield from response.iter_bytes()
        except httpx.RequestError as exc:
            raise ProviderError(
                "PROVIDER_CONNECTION_REQUIRED", "modal-2D Agent Artifact 读取失败", 503
            ) from exc

    def _descriptor(self, *, model_ids: list[str], health: str, status: str) -> dict[str, object]:
        return {
            "id": self.id,
            "displayName": "Modal 2D",
            "version": "1",
            "implementationRevision": "sana-sprint-v1",
            "health": health,
            "status": status,
            "contractVersion": "1",
            "artifactTransport": "connector-artifact",
            "capabilities": [
                {
                    "operation": MODAL_2D_OPERATION,
                    "version": "1",
                    "displayName": "SANA-Sprint Text to Image",
                    "category": "image-generation",
                    "status": status,
                    "input": {
                        "types": ["text"],
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["prompt"],
                            "properties": {
                                "prompt": {"type": "string", "minLength": 1, "maxLength": 4000},
                                "model": {"type": "string", "enum": model_ids},
                                "seed": {"type": "integer", "minimum": 0, "maximum": 2**32 - 1},
                                "guidance": {"type": "number", "minimum": 0, "maximum": 20},
                            },
                        },
                        "limits": {"width": 1024, "height": 1024, "steps": 2},
                    },
                    "output": {
                        "roles": [MODAL_2D_OUTPUT_ROLE],
                        "required": [MODAL_2D_OUTPUT_ROLE],
                        "optional": [],
                    },
                    "profiles": {"recommended": {"steps": 2, "guidance": 4.5}},
                    "optionsSchema": {"type": "object", "additionalProperties": False},
                    "execution": {
                        "async": True,
                        "stages": ["queued", "running", "artifact"],
                        "durationClass": "medium",
                        "costClass": "gpu",
                    },
                    "prerequisites": {"authMode": "connector-session", "connection": True},
                    "support": {"cancel": True, "resume": True, "idempotency": True},
                    "artifactTransport": "connector-artifact",
                }
            ],
        }

    def _job(self, payload: dict[str, object]) -> ProviderJob:
        job_id = str(payload.get("id") or "").strip()
        status = str(payload.get("status") or "").strip()
        if not job_id or status not in _PROVIDER_STATUSES:
            raise ProviderError("PROVIDER_JOB_INVALID", "modal-2D Job 响应无效", 502)
        artifact = None
        result = payload.get("result")
        if status == "succeeded":
            if not isinstance(result, dict) or not isinstance(result.get("artifact"), dict):
                raise ProviderError("PROVIDER_JOB_INVALID", "modal-2D 成功 Job 缺少 Artifact", 502)
            artifact = _artifact(result["artifact"])
        error_code = payload.get("error_code")
        retryable = payload.get("retryable")
        return ProviderJob(
            id=job_id,
            status=status,
            model=str(payload.get("model") or "").strip() or None,
            artifact=artifact,
            error_code=str(error_code).strip() if error_code else None,
            retryable=bool(retryable) if retryable is not None else None,
        )

    def _json(self, method: str, path: str, **kwargs) -> dict[str, object]:
        response = self._request(method, path, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("PROVIDER_RESPONSE_INVALID", "modal-2D 返回无效 JSON", 502) from exc
        if not isinstance(payload, dict):
            raise ProviderError("PROVIDER_RESPONSE_INVALID", "modal-2D 返回结构无效", 502)
        return payload

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = self._headers(kwargs.pop("headers", {}))
        try:
            response = self.client.request(
                method, f"{self.endpoint}{path}", headers=headers, **kwargs
            )
        except httpx.RequestError as exc:
            raise ProviderError(
                "PROVIDER_CONNECTION_REQUIRED", "modal-2D Agent 不可达", 503
            ) from exc
        self._ensure_success(response)
        return response

    def _headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        result = dict(headers or {})
        if self.token:
            result["X-Modal-2D-Session"] = self.token
        return result

    @staticmethod
    def _ensure_success(response: httpx.Response) -> None:
        if 200 <= response.status_code < 300:
            return
        if response.status_code in {401, 403, 409, 502, 503, 504}:
            raise ProviderError("PROVIDER_CONNECTION_REQUIRED", "modal-2D Agent 当前不可用", 503)
        raise ProviderError("PROVIDER_REQUEST_FAILED", f"modal-2D HTTP {response.status_code}", 502)


def _artifact(value: dict[str, object]) -> ProviderArtifact:
    artifact_id = _safe_id(str(value.get("id") or ""))
    role = str(value.get("role") or "").strip()
    mime = str(value.get("mime") or "").strip().lower()
    size = value.get("bytes")
    digest = str(value.get("sha256") or "").strip().lower()
    if role != MODAL_2D_OUTPUT_ROLE or mime != "image/png":
        raise ProviderError("PROVIDER_ARTIFACT_INVALID", "modal-2D Artifact role/mime 无效", 502)
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0 or size > 2**53 - 1:
        raise ProviderError("PROVIDER_ARTIFACT_INVALID", "modal-2D Artifact bytes 无效", 502)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ProviderError("PROVIDER_ARTIFACT_INVALID", "modal-2D Artifact sha256 无效", 502)
    return ProviderArtifact(id=artifact_id, role=role, mime=mime, bytes=size, sha256=digest)


def _safe_id(value: str) -> str:
    text = str(value or "").strip()
    if (
        not text
        or len(text) > 160
        or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for char in text
        )
    ):
        raise ProviderError("PROVIDER_ID_INVALID", "Provider ID 不是安全 opaque ID", 502)
    return text


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
        raise ValueError("modal-2D Agent endpoint 必须是裸 loopback http origin")
    return f"http://{parsed.netloc}"
