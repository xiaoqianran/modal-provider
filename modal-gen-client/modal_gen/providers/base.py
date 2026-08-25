from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderArtifact:
    id: str
    role: str
    mime: str
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ProviderJob:
    id: str
    status: str
    model: str | None = None
    artifact: ProviderArtifact | None = None
    error_code: str | None = None
    retryable: bool | None = None


class ProviderAdapter(Protocol):
    id: str

    def descriptor(self) -> dict[str, object]: ...

    def unavailable_descriptor(self) -> dict[str, object]: ...

    def submit(
        self,
        *,
        operation: str,
        inputs: dict[str, object],
        profile: str | None,
        options: dict[str, object],
    ) -> ProviderJob: ...

    def get(self, provider_job_id: str) -> ProviderJob: ...

    def cancel(self, provider_job_id: str) -> ProviderJob: ...

    def iter_artifact(
        self, provider_job_id: str, artifact: ProviderArtifact
    ) -> Iterator[bytes]: ...
