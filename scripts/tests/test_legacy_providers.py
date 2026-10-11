"""Compatibility checks for installed/legacy Provider layouts."""
import shutil
import tempfile
import unittest
from pathlib import Path

import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "check-legacy-providers.py"
spec = importlib.util.spec_from_file_location("legacy_providers", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
inspect_provider = module.inspect_provider

ROOT = Path(__file__).resolve().parents[2]


class LegacyProviderTests(unittest.TestCase):
    def test_production_layouts(self):
        for folder, package in (("modal-2D", "modal_2d"), ("modal-3D", "modal_3d"), ("modal-world", "modal_world")):
            with self.subTest(package=package):
                self.assertEqual(inspect_provider(ROOT / folder, package), [])

    def test_reject_missing_deployment_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            package = "modal_2d"
            shutil.copytree(ROOT / "modal-2D" / package, folder / package, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy2(ROOT / "modal-2D" / "pyproject.toml", folder / "pyproject.toml")
            manifest = folder / package / "deployment.py"
            content = manifest.read_text(encoding="utf-8")
            manifest.write_text(content.replace("def deployment_manifest(", "def renamed_manifest("), encoding="utf-8")
            self.assertTrue(any("deployment_manifest" in e for e in inspect_provider(folder, package)))
