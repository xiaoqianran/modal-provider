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
    def __init__(self, store: Store, adapters: list[ProviderAdapter], deployments=None) -> None:
        self.store = store
        self.adapters = {adapter.id: adapter for adapter in adapters}
        self.deployments = deployments
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
                descriptor = adapter.descriptor()
                providers.append(self._with_runtime_readiness(adapter.id, descriptor))
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

    async def snapshot_async(self, *, now: datetime | None = None) -> dict[str, object]:
        timestamp = now or datetime.now(UTC)
        providers: list[dict[str, object]] = []
        for adapter in self.adapters.values():
            try:
                descriptor = adapter.descriptor()
                providers.append(await self._with_runtime_readiness_async(adapter.id, descriptor))
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

    def _with_runtime_readiness(
        self, provider_id: str, descriptor: dict[str, object]
    ) -> dict[str, object]:
        if self.deployments is None or not self.deployments.connected:
            return descriptor
        readiness = self.deployments.cached_status(provider_id)
        if readiness is None:
            return descriptor
        return self._merge_runtime_readiness(descriptor, readiness)

    async def _with_runtime_readiness_async(
        self, provider_id: str, descriptor: dict[str, object]
    ) -> dict[str, object]:
        if self.deployments is None or not self.deployments.connected:
            return descriptor
        try:
            readiness = await self.deployments.status_async(provider_id)
        except Exception:
            return descriptor
        return self._merge_runtime_readiness(descriptor, readiness)

    @staticmethod
    def _merge_runtime_readiness(
        descriptor: dict[str, object], readiness: dict[str, object]
    ) -> dict[str, object]:
        providers = readiness.get("providers")
        if not isinstance(providers, list) or not providers:
            return descriptor
        runtime = providers[0]
        apps = runtime.get("apps") if isinstance(runtime, dict) else None
        if not isinstance(apps, list):
            return descriptor
        descriptor = dict(descriptor)
        descriptor["runtimeReadiness"] = runtime
        required_blockers = [
            {
                "app": str(item.get("app") or "unknown"),
                "status": str(item.get("status") or "unknown"),
                "error": item.get("error"),
            }
            for item in apps
            if isinstance(item, dict)
            and item.get("required") is True
            and item.get("status") != "current"
        ]
        required_bad = bool(required_blockers)
        ready_models = {
            model
            for item in apps
            if isinstance(item, dict) and item.get("status") == "current"
            for model in item.get("models", [])
            if isinstance(model, str)
        }
        capabilities = descriptor.get("capabilities")
        if not isinstance(capabilities, list):
            return descriptor
        updated = []
        any_available = False
        for capability in capabilities:
            if not isinstance(capability, dict):
                updated.append(capability)
                continue
            item = dict(capability)
            input_desc = item.get("input")
            if isinstance(input_desc, dict):
                input_desc = dict(input_desc)
                schema = input_desc.get("schema")
                if isinstance(schema, dict):
                    schema = dict(schema)
                    props = schema.get("properties")
                    if isinstance(props, dict) and isinstance(props.get("model"), dict):
                        props = dict(props)
                        model_schema = dict(props["model"])
                        enum = model_schema.get("enum")
                        if isinstance(enum, list):
                            model_schema["enum"] = [m for m in enum if m in ready_models]
                            item["readyModels"] = list(model_schema["enum"])
                            if not model_schema["enum"]:
                                item["status"] = "disabled"
                            elif required_bad:
                                item["status"] = "degraded"
                                item["runtimeBlockers"] = required_blockers
                                any_available = True
                            else:
                                any_available = True
                        props["model"] = model_schema
                        schema["properties"] = props
                    input_desc["schema"] = schema
                item["input"] = input_desc
            updated.append(item)
        descriptor["capabilities"] = updated
        if not any_available:
            descriptor["status"] = "disabled"
            descriptor["health"] = "unavailable"
        elif required_bad:
            descriptor["status"] = "degraded"
            descriptor["health"] = "degraded"
            descriptor["runtimeBlockers"] = required_blockers
        return descriptor

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

    async def connect_all_async(self, token_id: str, token_secret: str) -> list[dict[str, object]]:
        if not token_id.strip() or not token_secret.strip():
            raise ProviderError("PROVIDER_CREDENTIALS_REQUIRED", "Modal credentials 不能为空", 422)
        rows: list[dict[str, object]] = []
        connected: list[ProviderAdapter] = []
        try:
            for adapter in self.adapters.values():
                try:
                    connect_async = getattr(adapter, "connect_async", None)
                    if callable(connect_async):
                        rows.append(await connect_async(token_id, token_secret))
                    else:
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
            raise
        await self.snapshot_async()
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
