from __future__ import annotations

from dataclasses import dataclass

from .gateway.api import create_app as create_gateway_app
from .gateway.sessions import SessionService
from .generation.service import GenerationService
from .storage import Store


@dataclass(slots=True)
class Runtime(GenerationService):
    sessions: SessionService


def build_runtime(store: Store | None = None, *, adapters=None) -> Runtime:
    generation = GenerationService.build(store, adapters=adapters)
    return Runtime(
        store=generation.store,
        capabilities=generation.capabilities,
        jobs=generation.jobs,
        artifacts=generation.artifacts,
        sessions=SessionService(generation.store, generation.capabilities),
    )


_default_runtime: Runtime | None = None


def runtime() -> Runtime:
    global _default_runtime
    if _default_runtime is None:
        _default_runtime = build_runtime()
    return _default_runtime


def create_app(state: Runtime | None = None):
    return create_gateway_app(state, runtime_factory=runtime)


app = create_app()
