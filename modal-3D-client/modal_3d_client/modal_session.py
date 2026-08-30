from __future__ import annotations

import threading

import modal

_lock = threading.RLock()
_client: modal.Client | None = None


class NotConnectedError(RuntimeError):
    pass


def connect(token_id: str, token_secret: str) -> None:
    global _client
    candidate = modal.Client.from_credentials(token_id.strip(), token_secret.strip())
    candidate.hello()
    with _lock:
        _client = candidate


async def connect_async(token_id: str, token_secret: str) -> None:
    global _client
    candidate = await modal.Client.from_credentials.aio(token_id.strip(), token_secret.strip())
    await candidate.hello.aio()
    with _lock:
        _client = candidate


def disconnect() -> None:
    global _client
    with _lock:
        _client = None


def connected() -> bool:
    with _lock:
        return _client is not None


def client() -> modal.Client:
    with _lock:
        if _client is None:
            raise NotConnectedError("Modal connection required")
        return _client
