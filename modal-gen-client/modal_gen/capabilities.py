from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from .constants import CONNECTOR_ID, CONNECTOR_VERSION, CONTRACT_VERSION
from .errors import ProviderError
from .providers.protocol import ProviderAdapter
from .storage import Store


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CapabilityRegistry:
    def __init__(self, store: Store, adapters: list[ProviderAdapter]) -> None:
        self.store = store
        self.adapters = {adapter.id: adapter for adapter in adapters}
        if len(self.adapters) != len(adapters):
            raise ValueError("duplicate provider adapter")
        self.connector = {
            "id": CONNECTOR_ID,
            "instance": store.instance_id(),
            "version": CONNECTOR_VERSION,
        }

    def snapshot(self, *, now: datetime | None = None) -> dict[str, object]:
        timestamp = now or datetime.now(UTC)
        providers: list[dict[str, object]] = []
        for adapter in self.adapters.values():
            try:
                providers.append(adapter.descriptor())
            except ProviderError:
                providers.append(adapter.unavailable_descriptor())
        canonical = {
            "contractVersion": CONTRACT_VERSION,
            "connector": self.connector,
            "providers": providers,
        }
        digest = hashlib.sha256(
            json.dumps(
                canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        snapshot = {
            **canonical,
            "revision": f"caprev_{digest[:24]}",
            "hash": f"sha256:{digest}",
            "generatedAt": iso(timestamp),
            "expiresAt": iso(timestamp + timedelta(minutes=30)),
            "cachePolicy": {"maxAgeSeconds": 60},
        }
        self.store.save_snapshot(snapshot)
        return snapshot

    def get(self, hash_value: str) -> dict[str, object] | None:
        return self.store.get_snapshot(hash_value)

    def adapter(self, provider_id: str) -> ProviderAdapter:
        try:
            return self.adapters[provider_id]
        except KeyError as exc:
            raise ProviderError(
                "PROVIDER_UNAVAILABLE", f"Provider 不存在: {provider_id}", 422
            ) from exc

    def connections(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for adapter in self.adapters.values():
            try:
                rows.append(adapter.connection_status())
            except (AttributeError, ProviderError):
                rows.append({"id": adapter.id, "connected": True, "managed": False})
        return rows

    def connect_all(self, token_id: str, token_secret: str) -> list[dict[str, object]]:
        if not token_id.strip() or not token_secret.strip():
            raise ProviderError("PROVIDER_CREDENTIALS_REQUIRED", "Modal credentials 不能为空", 422)
        rows: list[dict[str, object]] = []
        connected: list[ProviderAdapter] = []
        try:
            for adapter in self.adapters.values():
                try:
                    rows.append(adapter.connect(token_id, token_secret))
                    connected.append(adapter)
                except AttributeError:
                    rows.append({"id": adapter.id, "connected": True, "managed": False})
        except Exception:
            for adapter in reversed(connected):
                try:
                    adapter.disconnect()
                except Exception:
                    pass
            self.snapshot()
            raise
        self.snapshot()
        return rows

    def disconnect_all(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for adapter in self.adapters.values():
            try:
                rows.append(adapter.disconnect())
            except AttributeError:
                rows.append({"id": adapter.id, "connected": True, "managed": False})
        self.snapshot()
        return rows

    @staticmethod
    def capability(
        snapshot: dict[str, object], provider_id: str, operation: str
    ) -> dict[str, object]:
        providers = snapshot.get("providers")
        if not isinstance(providers, list):
            raise ProviderError("CAPABILITY_INVALID", "Capability snapshot 无效", 500)
        for provider in providers:
            if not isinstance(provider, dict) or provider.get("id") != provider_id:
                continue
            if provider.get("status") != "available" or provider.get("health") == "unavailable":
                raise ProviderError("JOB_CAPABILITY_UNAVAILABLE", "Provider 当前不可用", 409)
            capabilities = provider.get("capabilities")
            if not isinstance(capabilities, list):
                break
            for capability in capabilities:
                if isinstance(capability, dict) and capability.get("operation") == operation:
                    if capability.get("status") != "available":
                        raise ProviderError(
                            "JOB_CAPABILITY_UNAVAILABLE", "Capability 当前不可用", 409
                        )
                    return {"provider": provider, "capability": capability}
        raise ProviderError("JOB_CAPABILITY_UNAVAILABLE", "Capability 未注册", 409)
