"""Load targets from canonical Provider deployment manifests."""

from __future__ import annotations

import importlib

MANIFEST_MODULES = {
    "modal-2d": "modal_2d.deployment",
    "modal-3d": "modal_3d.deployment",
    "modal-world": "modal_world.deployment",
}


class ManifestAdapter:
    def __init__(self, provider: str, module: str) -> None:
        self.id = provider
        self.module = module

    def deployment_manifest(self):
        return importlib.import_module(self.module).deployment_manifest()


def load_manifest_adapters():
    return [ManifestAdapter(provider, module) for provider, module in MANIFEST_MODULES.items()]
