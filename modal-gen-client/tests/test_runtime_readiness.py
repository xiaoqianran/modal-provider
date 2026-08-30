from __future__ import annotations

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

    def status(self, _provider):
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


def test_required_runtime_disables_provider(tmp_path):
    registry = CapabilityRegistry(
        Store(tmp_path / "db.sqlite3"), [Adapter()], Deployments(required_status="missing")
    )
    provider = registry.snapshot()["providers"][0]
    assert provider["status"] == "disabled"
    assert provider["health"] == "unavailable"
    assert provider["capabilities"][0]["status"] == "disabled"
