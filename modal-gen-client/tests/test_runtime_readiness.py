from __future__ import annotations

import asyncio

from modal_gen.capabilities import CapabilityRegistry
from modal_gen.storage import Store


class Adapter:
    id = "modal-x"

    def descriptor(self):
        return {
            "id": self.id,
            "status": "available",
            "health": "healthy",
            "capabilities": [
                {
                    "operation": "generate",
                    "status": "available",
                    "input": {
                        "schema": {
                            "properties": {"model": {"type": "string", "enum": ["ready", "stale"]}}
                        }
                    },
                }
            ],
        }

    def unavailable_descriptor(self):
        return {"id": self.id, "status": "disabled", "health": "unavailable", "capabilities": []}


class Deployments:
    connected = True

    def __init__(self, required_status="current"):
        self.required_status = required_status

    def cached_status(self, _provider):
        return {
            "providers": [
                {
                    "id": "modal-x",
                    "status": "partial",
                    "apps": [
                        {
                            "app": "prep",
                            "status": self.required_status,
                            "required": True,
                            "models": [],
                        },
                        {
                            "app": "ready-app",
                            "status": "current",
                            "required": False,
                            "models": ["ready"],
                        },
                        {
                            "app": "stale-app",
                            "status": "stale",
                            "required": False,
                            "models": ["stale"],
                        },
                    ],
                }
            ]
        }


def test_readiness_filters_non_current_models(tmp_path):
    registry = CapabilityRegistry(Store(tmp_path / "db.sqlite3"), [Adapter()], Deployments())
    provider = registry.snapshot()["providers"][0]
    capability = provider["capabilities"][0]
    assert capability["input"]["schema"]["properties"]["model"]["enum"] == ["ready"]
    assert capability["status"] == "available"
    assert provider["status"] == "available"
    assert provider["runtimeReadiness"]["apps"][2]["status"] == "stale"
    assert capability["declaredModels"] == ["ready", "stale"]
    assert capability["modelReadiness"] == [
        {
            "model": "ready",
            "app": "ready-app",
            "state": "ready",
            "runnable": True,
            "deploymentStatus": "current",
            "weightsStatus": "not_required",
            "error": None,
        },
        {
            "model": "stale",
            "app": "stale-app",
            "state": "outdated",
            "runnable": False,
            "deploymentStatus": "stale",
            "weightsStatus": "not_required",
            "error": None,
        },
    ]


def test_required_runtime_degrades_provider_when_worker_is_ready(tmp_path):
    registry = CapabilityRegistry(
        Store(tmp_path / "db.sqlite3"), [Adapter()], Deployments(required_status="missing")
    )
    provider = registry.snapshot()["providers"][0]
    assert provider["status"] == "degraded"
    assert provider["health"] == "degraded"
    capability = provider["capabilities"][0]
    assert capability["status"] == "degraded"
    assert capability["readyModels"] == ["ready"]
    assert capability["runtimeBlockers"] == [{"app": "prep", "status": "missing", "error": None}]


def test_async_snapshot_can_force_runtime_readiness_refresh(tmp_path):
    calls = []

    class AsyncDeployments(Deployments):
        async def status_async(self, provider, *, force=False):
            calls.append((provider, force))
            return self.cached_status(provider)

    registry = CapabilityRegistry(Store(tmp_path / "db.sqlite3"), [Adapter()], AsyncDeployments())
    snapshot = asyncio.run(registry.snapshot_async(force_runtime=True))

    assert snapshot["providers"][0]["status"] == "available"
    assert calls == [("modal-x", True)]


def test_async_readiness_failure_fails_closed(tmp_path):
    class BrokenDeployments(Deployments):
        async def status_async(self, _provider, *, force=False):
            assert force is True
            raise RuntimeError("control plane unavailable")

    registry = CapabilityRegistry(Store(tmp_path / "db.sqlite3"), [Adapter()], BrokenDeployments())
    provider = asyncio.run(registry.snapshot_async(force_runtime=True))["providers"][0]
    capability = provider["capabilities"][0]

    assert provider["status"] == "disabled"
    assert provider["health"] == "unavailable"
    assert capability["status"] == "disabled"
    assert capability["input"]["schema"]["properties"]["model"]["enum"] == []
    assert capability["readyModels"] == []
    assert {row["state"] for row in capability["modelReadiness"]} == {"error"}
    assert "control plane unavailable" in capability["runtimeBlockers"][0]["error"]


def test_sync_readiness_without_cache_does_not_query_live_status(tmp_path):
    calls = []

    class UncachedDeployments(Deployments):
        def cached_status(self, _provider):
            return None

        def status(self, provider):
            calls.append(provider)
            raise AssertionError("sync snapshot must not query the Modal control plane")

    registry = CapabilityRegistry(
        Store(tmp_path / "db.sqlite3"), [Adapter()], UncachedDeployments()
    )
    provider = registry.snapshot()["providers"][0]

    assert provider["status"] == "available"
    assert "runtimeReadiness" not in provider
    assert calls == []


def test_submission_runtime_gate_rejects_missing_selected_worker(tmp_path):
    class SubmissionDeployments:
        connected = True

        @staticmethod
        def manages_provider(provider):
            return provider == "modal-x"

        @staticmethod
        def submission_status(provider, model):
            assert (provider, model) == ("modal-x", "ready")
            return {
                "providers": [
                    {
                        "id": "modal-x",
                        "status": "partial",
                        "apps": [
                            {
                                "app": "ready-app",
                                "status": "missing",
                                "required": False,
                                "models": ["ready"],
                                "error": "App not found",
                            }
                        ],
                    }
                ]
            }

    registry = CapabilityRegistry(
        Store(tmp_path / "db.sqlite3"), [Adapter()], SubmissionDeployments()
    )

    try:
        registry.ensure_submission_ready("modal-x", "generate", {"model": "ready"})
    except Exception as exc:
        assert getattr(exc, "code", None) == "JOB_RUNTIME_UNAVAILABLE"
    else:
        raise AssertionError("missing worker must block submission")
