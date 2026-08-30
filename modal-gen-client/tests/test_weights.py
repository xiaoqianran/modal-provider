from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from modal_gen.weights import PrepareCall, WeightProvisioner, WeightSpec


def _spec() -> WeightSpec:
    return WeightSpec(
        volume="model-weights",
        required_paths=("model/config.json", "model/model.bin"),
        prepare=(PrepareCall("runtime.worker", "sync_weights", ("model-a",)),),
    )


def test_cached_weights_skip_preparation(monkeypatch):
    class Volume:
        def listdir(self, _path):
            return [SimpleNamespace(size=1)]

    monkeypatch.setattr(
        "modal_gen.weights.modal.Volume.from_name",
        lambda *_args, **_kwargs: Volume(),
    )
    monkeypatch.setattr(
        "modal_gen.weights.importlib.import_module",
        lambda _name: pytest.fail("cached weights must not start a preparation app"),
    )

    result = WeightProvisioner().ensure("worker", (_spec(),), SimpleNamespace())
    assert result["status"] == "ready"


def test_missing_weights_are_downloaded_and_verified(monkeypatch):
    ready = False
    events = []

    class Volume:
        def listdir(self, _path):
            return [SimpleNamespace(size=1)] if ready else []

    class Function:
        def remote(self, *arguments):
            nonlocal ready
            events.append(("remote", arguments))
            ready = True

    class App:
        def run(self, **kwargs):
            events.append(("run", kwargs["name"]))
            return nullcontext()

    module = SimpleNamespace(app=App(), sync_weights=Function())
    monkeypatch.setattr(
        "modal_gen.weights.modal.Volume.from_name",
        lambda *_args, **_kwargs: Volume(),
    )
    monkeypatch.setattr(
        "modal_gen.weights.importlib.import_module",
        lambda _name: module,
    )

    phases = []
    result = WeightProvisioner().ensure(
        "worker",
        (_spec(),),
        SimpleNamespace(),
        on_phase=phases.append,
    )

    assert result["status"] == "downloaded"
    assert events == [("run", "worker-weights"), ("remote", ("model-a",))]
    assert phases == ["checking_weights", "downloading_weights", "verifying_weights"]


def test_incomplete_preparation_fails_closed(monkeypatch):
    class Volume:
        def listdir(self, _path):
            return []

    module = SimpleNamespace(
        app=SimpleNamespace(run=lambda **_kwargs: nullcontext()),
        sync_weights=SimpleNamespace(remote=lambda *_args: None),
    )
    monkeypatch.setattr(
        "modal_gen.weights.modal.Volume.from_name",
        lambda *_args, **_kwargs: Volume(),
    )
    monkeypatch.setattr(
        "modal_gen.weights.importlib.import_module",
        lambda _name: module,
    )

    with pytest.raises(RuntimeError, match="did not create required files"):
        WeightProvisioner().ensure("worker", (_spec(),), SimpleNamespace())


@pytest.mark.parametrize(
    "path",
    ["", "/", "/model.bin", "../model.bin", "model/../secret", r"model\secret"],
)
def test_manifest_rejects_unsafe_required_paths(path):
    with pytest.raises(ValueError, match="safe relative path"):
        WeightSpec.from_manifest(
            {
                "volume": "weights",
                "requiredPaths": [path],
                "prepare": [{"function": "sync_weights"}],
            },
            default_module="runtime.worker",
        )


def test_status_async_lists_each_volume_once(monkeypatch):
    import asyncio

    calls = []

    class AsyncListDir:
        async def aio(self, path, *, recursive=False):
            calls.append((path, recursive))
            return [
                SimpleNamespace(path="model/config.json", size=1),
                SimpleNamespace(path="model/model.bin", size=2),
                SimpleNamespace(path="other/file.bin", size=3),
            ]

    class Volume:
        listdir = AsyncListDir()

    monkeypatch.setattr(
        "modal_gen.weights.modal.Volume.from_name",
        lambda *_args, **_kwargs: Volume(),
    )
    spec2 = WeightSpec(
        volume="model-weights",
        required_paths=("other/file.bin",),
        prepare=(PrepareCall("runtime.worker", "sync_weights"),),
    )

    result = asyncio.run(WeightProvisioner().status_async((_spec(), spec2), SimpleNamespace()))

    assert result["status"] == "ready"
    assert calls == [("/", True)]


def test_status_async_reuses_volume_cache(monkeypatch):
    import asyncio

    calls = 0

    class AsyncListDir:
        async def aio(self, _path, *, recursive=False):
            nonlocal calls
            calls += 1
            assert recursive is True
            return [
                SimpleNamespace(path="model/config.json", size=1),
                SimpleNamespace(path="model/model.bin", size=1),
            ]

    class Volume:
        listdir = AsyncListDir()

    monkeypatch.setattr(
        "modal_gen.weights.modal.Volume.from_name",
        lambda *_args, **_kwargs: Volume(),
    )
    provisioner = WeightProvisioner(status_cache_ttl_s=60)

    async def scenario():
        first = await provisioner.status_async((_spec(),), SimpleNamespace())
        second = await provisioner.status_async((_spec(),), SimpleNamespace())
        return first, second

    first, second = asyncio.run(scenario())
    assert first == second
    assert first["status"] == "ready"
    assert calls == 1


def test_status_async_uses_stale_cache_on_volume_rate_limit(monkeypatch):
    import asyncio

    responses = [
        [
            SimpleNamespace(path="model/config.json", size=1),
            SimpleNamespace(path="model/model.bin", size=1),
        ],
        RuntimeError("VolumeListFiles rate limit exceeded. Please wait and retry."),
    ]

    class AsyncListDir:
        async def aio(self, _path, *, recursive=False):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    class Volume:
        listdir = AsyncListDir()

    monkeypatch.setattr(
        "modal_gen.weights.modal.Volume.from_name",
        lambda *_args, **_kwargs: Volume(),
    )
    provisioner = WeightProvisioner(status_cache_ttl_s=0)

    async def scenario():
        first = await provisioner.status_async((_spec(),), SimpleNamespace())
        second = await provisioner.status_async((_spec(),), SimpleNamespace())
        return first, second

    first, second = asyncio.run(scenario())
    assert first["status"] == "ready"
    assert second == first
    assert responses == []
