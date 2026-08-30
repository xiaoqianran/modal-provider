from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib.metadata import entry_points
from typing import Any

from ..errors import ProviderError
from .protocol import (
    LibraryProvider,
    ProviderAdapter,
    ProviderArtifact,
    ProviderContext,
    ProviderJob,
)

_ENTRYPOINT_GROUP = "modal_gen.providers"
_STATUSES = {
    "running",
    "succeeded",
    "failed",
    "cancel_requested",
    "connection_required",
    "cancelled",
    "expired",
}


class LibraryProviderAdapter:
    """Normalize an installed provider package into the Connector SPI."""

    def __init__(self, provider: LibraryProvider) -> None:
        provider_id = str(getattr(provider, "id", "")).strip()
        if not provider_id:
            raise ValueError("provider id is required")
        self.id = provider_id
        self.provider = provider

    def descriptor(self) -> dict[str, object]:
        value = dict(self._call(self.provider.descriptor))
        if value.get("id") != self.id:
            raise ProviderError("PROVIDER_CAPABILITY_INVALID", "Provider identity 不匹配", 502)
        return value

    def unavailable_descriptor(self) -> dict[str, object]:
        value = dict(self.provider.unavailable_descriptor())
        if value.get("id") != self.id:
            raise ProviderError("PROVIDER_CAPABILITY_INVALID", "Provider identity 不匹配", 502)
        return value

    def connection_status(self) -> dict[str, object]:
        value = dict(self.provider.connection_status())
        return {"id": self.id, **value}

    def connect(self, token_id: str, token_secret: str) -> dict[str, object]:
        try:
            value = dict(self.provider.connect(token_id, token_secret))
        except Exception as exc:
            detail = type(exc).__name__
            raise ProviderError(
                "PROVIDER_CONNECTION_FAILED",
                f"{self.id} 连接 Modal 失败 ({detail})",
                502,
            ) from exc
        return {"id": self.id, **value}

    async def connect_async(self, token_id: str, token_secret: str) -> dict[str, object]:
        try:
            connect_async = getattr(self.provider, "connect_async", None)
            if callable(connect_async):
                value = dict(await connect_async(token_id, token_secret))
            else:
                value = dict(self.provider.connect(token_id, token_secret))
        except Exception as exc:
            detail = type(exc).__name__
            raise ProviderError(
                "PROVIDER_CONNECTION_FAILED",
                f"{self.id} 连接 Modal 失败 ({detail})",
                502,
            ) from exc
        return {"id": self.id, **value}

    def disconnect(self) -> dict[str, object]:
        try:
            value = dict(self.provider.disconnect())
        except Exception as exc:
            detail = type(exc).__name__
            raise ProviderError(
                "PROVIDER_DISCONNECT_FAILED",
                f"{self.id} 断开 Modal 失败 ({detail})",
                502,
            ) from exc
        return {"id": self.id, **value}

    def deployment_manifest(self) -> dict[str, object]:
        factory = getattr(self.provider, "deployment_manifest", None)
        if not callable(factory):
            return {"provider": self.id, "targets": []}
        value = dict(factory())
        if value.get("provider") != self.id or not isinstance(value.get("targets"), list):
            raise ProviderError(
                "PROVIDER_DEPLOYMENT_INVALID", "Provider deployment manifest 无效", 502
            )
        return value

    def submit(
        self,
        *,
        operation: str,
        inputs: dict[str, object],
        profile: str | None,
        options: dict[str, object],
        context: ProviderContext,
    ) -> ProviderJob:
        return self._job(
            self._call(
                self.provider.submit,
                operation=operation,
                inputs=inputs,
                profile=profile,
                options=options,
                context=context,
            )
        )

    def get(self, provider_job_id: str) -> ProviderJob:
        return self._job(self._call(self.provider.get, provider_job_id))

    def cancel(self, provider_job_id: str) -> ProviderJob:
        return self._job(self._call(self.provider.cancel, provider_job_id))

    def iter_artifact(self, provider_job_id: str, artifact: ProviderArtifact):
        try:
            yield from self.provider.iter_artifact(provider_job_id, artifact.id)
        except ProviderError:
            raise
        except Exception as exc:
            raise self._provider_error(exc, "PROVIDER_ARTIFACT_READ_FAILED", 502) from exc

    def _job(self, value: object) -> ProviderJob:
        if not isinstance(value, Mapping):
            raise ProviderError("PROVIDER_JOB_INVALID", "Provider Job 必须是对象", 502)
        job_id = _text(value.get("id"))
        status = _text(value.get("status"))
        if not job_id or status not in _STATUSES:
            raise ProviderError("PROVIDER_JOB_INVALID", "Provider Job identity/status 无效", 502)
        raw_artifacts = value.get("artifacts") or []
        if not isinstance(raw_artifacts, list):
            raise ProviderError("PROVIDER_JOB_INVALID", "Provider artifacts 必须是数组", 502)
        artifacts = tuple(_artifact(item) for item in raw_artifacts)
        if status == "succeeded" and not artifacts:
            raise ProviderError("PROVIDER_JOB_INVALID", "成功 Provider Job 缺少 Artifact", 502)
        model = _text(value.get("model")) or None
        error_code = _text(value.get("error_code")) or None
        retryable = value.get("retryable")
        return ProviderJob(
            id=job_id,
            status=status,
            model=model,
            artifacts=artifacts,
            error_code=error_code,
            retryable=bool(retryable) if retryable is not None else None,
        )

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ProviderError:
            raise
        except Exception as exc:
            raise self._provider_error(exc, "PROVIDER_REQUEST_FAILED", 502) from exc

    @staticmethod
    def _provider_error(exc: Exception, default_code: str, default_status: int) -> ProviderError:
        code = str(getattr(exc, "code", "") or default_code)
        status = getattr(exc, "status", default_status)
        if not isinstance(status, int) or isinstance(status, bool):
            status = default_status
        message = str(exc).strip() or "Provider 调用失败"
        return ProviderError(code, message, status)


def load_providers(*, group: str = _ENTRYPOINT_GROUP) -> list[ProviderAdapter]:
    loaded: list[ProviderAdapter] = []
    for entry in sorted(entry_points(group=group), key=lambda item: item.name):
        factory = entry.load()
        provider = factory()
        loaded.append(LibraryProviderAdapter(provider))
    if not loaded:
        raise RuntimeError(f"no providers installed for entry point group {group!r}")
    return loaded


def adapt_providers(providers: Iterable[LibraryProvider]) -> list[ProviderAdapter]:
    return [LibraryProviderAdapter(provider) for provider in providers]


def _artifact(value: object) -> ProviderArtifact:
    if not isinstance(value, Mapping):
        raise ProviderError("PROVIDER_ARTIFACT_INVALID", "Provider Artifact 必须是对象", 502)
    artifact_id = _text(value.get("id"))
    role = _text(value.get("role"))
    mime = _text(value.get("mime")).lower()
    size = value.get("bytes")
    digest = _text(value.get("sha256")).lower()
    if not artifact_id or not role or not mime:
        raise ProviderError("PROVIDER_ARTIFACT_INVALID", "Provider Artifact identity 无效", 502)
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ProviderError("PROVIDER_ARTIFACT_INVALID", "Provider Artifact bytes 无效", 502)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ProviderError("PROVIDER_ARTIFACT_INVALID", "Provider Artifact sha256 无效", 502)
    return ProviderArtifact(
        id=artifact_id,
        role=role,
        mime=mime,
        bytes=size,
        sha256=digest,
    )


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
