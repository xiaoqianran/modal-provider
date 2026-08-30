from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DeployScriptTests(unittest.TestCase):
    def test_powershell_module_replacement_is_quoted(self) -> None:
        script = (PROJECT_ROOT / "scripts/deploy-worker.ps1").read_text(encoding="utf-8")
        self.assertIn("-replace '[\\\\/]', '.'", script)
        self.assertNotIn("-replace [\\/], .", script)
