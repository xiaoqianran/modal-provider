from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import modal
from modal.exception import NotFoundError


@dataclass(frozen=True, slots=True)
class PrepareCall:
    module: str
    function: str
    arguments: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class WeightSpec:
    volume: str
    required_paths: tuple[str, ...]
    prepare: tuple[PrepareCall, ...]

    @classmethod
    def from_manifest(cls, value: object, *, default_module: str) -> WeightSpec:
        if not isinstance(value, dict):
            raise ValueError("weight spec must be an object")
        volume = str(value.get("volume") or "").strip()
        raw_paths = value.get("requiredPaths")
        raw_prepare = value.get("prepare")
        if not volume or not isinstance(raw_paths, list) or not raw_paths:
            raise ValueError("weight spec requires volume and requiredPaths")
        paths = tuple(_clean_path(path) for path in raw_paths)
        if not isinstance(raw_prepare, list) or not raw_prepare:
            raise ValueError("weight spec requires at least one prepare call")
        calls = tuple(_prepare_call(item, default_module) for item in raw_prepare)
        return cls(volume=volume, required_paths=paths, prepare=calls)


class WeightProvisioner:
    """Ensure declared Modal Volume files exist before a runtime is deployed."""

    def __init__(self, *, status_cache_ttl_s: float = 45.0) -> None:
        if status_cache_ttl_s < 0:
            raise ValueError("status_cache_ttl_s must be non-negative")
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._status_cache_ttl_s = status_cache_ttl_s
        self._status_cache: dict[tuple[str, str | None], tuple[float, frozenset[str]]] = {}

    def status(
        self,
        specs: tuple[WeightSpec, ...],
        client: modal.Client,
        environment_name: str | None = None,
    ) -> dict[str, object]:
        volumes = [self._volume_status(spec, client, environment_name) for spec in specs]
        return {
            "status": "ready" if all(item["status"] == "ready" for item in volumes) else "missing",
            "volumes": volumes,
        }

    async def status_async(
        self,
        specs: tuple[WeightSpec, ...],
        client: modal.Client,
        environment_name: str | None = None,
    ) -> dict[str, object]:
        snapshots: dict[str, frozenset[str]] = {}
        for volume_name in dict.fromkeys(spec.volume for spec in specs):
            snapshots[volume_name] = await self._volume_files_async(
                volume_name, client, environment_name
            )
        volumes = [
            self._volume_row(
                spec,
                "ready"
                if _required_paths_ready(spec.required_paths, snapshots[spec.volume])
                else "missing",
            )
            for spec in specs
        ]
        return {
            "status": "ready" if all(item["status"] == "ready" for item in volumes) else "missing",
            "volumes": volumes,
        }

    def ensure(
        self,
        runtime_name: str,
        specs: tuple[WeightSpec, ...],
        client: modal.Client,
        environment_name: str | None = None,
        *,
        on_phase: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        if not specs:
            return {"status": "not_required", "volumes": []}
        _notify(on_phase, "checking_weights")
        downloaded = False
        volumes: list[dict[str, object]] = []
        for spec in specs:
            with self._volume_lock(spec.volume):
                if self._ready(spec, client, environment_name):
                    volumes.append(self._volume_row(spec, "ready"))
                    continue
                downloaded = True
                _notify(on_phase, "downloading_weights")
                self._prepare(runtime_name, spec, client, environment_name)
                _notify(on_phase, "verifying_weights")
                if not self._ready(spec, client, environment_name):
                    missing = ", ".join(spec.required_paths)
                    raise RuntimeError(
                        f"weight preparation did not create required files in "
                        f"{spec.volume}: {missing}"
                    )
                volumes.append(self._volume_row(spec, "downloaded"))
        return {"status": "downloaded" if downloaded else "ready", "volumes": volumes}

    def _volume_lock(self, volume: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(volume, threading.Lock())

    def _volume_status(
        self,
        spec: WeightSpec,
        client: modal.Client,
        environment_name: str | None,
    ) -> dict[str, object]:
        return self._volume_row(
            spec,
            "ready" if self._ready(spec, client, environment_name) else "missing",
        )

    @staticmethod
    def _volume_row(spec: WeightSpec, status: str) -> dict[str, object]:
        return {
            "name": spec.volume,
            "status": status,
            "requiredPaths": list(spec.required_paths),
        }

    @staticmethod
    def _ready(
        spec: WeightSpec,
        client: modal.Client,
        environment_name: str | None,
    ) -> bool:
        try:
            volume = modal.Volume.from_name(
                spec.volume,
                environment_name=environment_name,
                client=client,
            )
            for path in spec.required_paths:
                entries = volume.listdir(path)
                sizes = (int(getattr(entry, "size", 0) or 0) for entry in entries)
                if not entries or max(sizes) <= 0:
                    return False
            return True
        except NotFoundError:
            return False

    async def _volume_files_async(
        self,
        volume_name: str,
        client: modal.Client,
        environment_name: str | None,
    ) -> frozenset[str]:
        key = (volume_name, environment_name)
        now = time.monotonic()
        with self._guard:
            cached = self._status_cache.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]

        try:
            volume = modal.Volume.from_name(
                volume_name,
                environment_name=environment_name,
                client=client,
            )
            entries = await volume.listdir.aio("/", recursive=True)
            files = frozenset(
                str(getattr(entry, "path", "") or "").lstrip("/")
                for entry in entries
                if int(getattr(entry, "size", 0) or 0) > 0
            )
        except NotFoundError:
            files = frozenset()
        except Exception as exc:
            with self._guard:
                stale = self._status_cache.get(key)
            if stale is not None and _is_volume_rate_limit(exc):
                return stale[1]
            raise

        with self._guard:
            self._status_cache[key] = (now + self._status_cache_ttl_s, files)
        return files

    @staticmethod
    def _prepare(
        runtime_name: str,
        spec: WeightSpec,
        client: modal.Client,
        environment_name: str | None,
    ) -> None:
        modules = dict.fromkeys(call.module for call in spec.prepare)
        for module_name in modules:
            module = importlib.import_module(module_name)
            app = module.app
            calls = (call for call in spec.prepare if call.module == module_name)
            with app.run(
                name=f"{runtime_name}-weights",
                client=client,
                environment_name=environment_name,
            ):
                for call in calls:
                    getattr(module, call.function).remote(*call.arguments)


def _required_paths_ready(required_paths: tuple[str, ...], files: frozenset[str]) -> bool:
    for required in required_paths:
        prefix = required.rstrip("/") + "/"
        if required not in files and not any(path.startswith(prefix) for path in files):
            return False
    return True


def _is_volume_rate_limit(exc: Exception) -> bool:
    message = str(exc).lower()
    return "volumelistfiles" in message and "rate limit" in message


def _clean_path(value: object) -> str:
    path = str(value or "").strip()
    parts = path.split("/")
    if (
        not path
        or path.startswith(("/", "\\"))
        or "\\" in path
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("weight requiredPath must be a safe relative path")
    return path


def _prepare_call(value: object, default_module: str) -> PrepareCall:
    if not isinstance(value, dict):
        raise ValueError("weight prepare call must be an object")
    module = str(value.get("module") or default_module).strip()
    function = str(value.get("function") or "").strip()
    arguments = value.get("arguments", [])
    if not module or not function or not isinstance(arguments, list):
        raise ValueError("weight prepare call is invalid")
    return PrepareCall(module=module, function=function, arguments=tuple(arguments))


def _notify(callback: Callable[[str], None] | None, phase: str) -> None:
    if callback is not None:
        callback(phase)
