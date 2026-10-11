from __future__ import annotations

from dataclasses import dataclass

from ..providers.loader import load_providers
from ..storage import Store
from .artifacts import ArtifactService
from .capabilities import CapabilityRegistry
from .jobs import JobService


@dataclass(slots=True)
class GenerationService:
    """Shared generation services for Connector and Studio.

    JobService owns submission validation, idempotency and provider dispatch.
    ArtifactService supplies verified inputs and projects provider outputs.
    """

    store: Store
    capabilities: CapabilityRegistry
    jobs: JobService
    artifacts: ArtifactService

    @classmethod
    def build(cls, store: Store | None = None, *, adapters=None) -> GenerationService:
        state = store if store is not None else Store()
        providers = adapters if adapters is not None else load_providers()
        capabilities = CapabilityRegistry(state, providers)
        artifacts = ArtifactService(state, capabilities)
        return cls(state, capabilities, JobService(state, capabilities, artifacts), artifacts)
