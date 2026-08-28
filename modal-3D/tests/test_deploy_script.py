from __future__ import annotations

import unittest
from pathlib import Path


class DeployScriptTests(unittest.TestCase):
    def test_powershell_module_replacement_is_quoted(self) -> None:
        script = Path("scripts/deploy-worker.ps1").read_text()
        self.assertIn("-replace '[\\\\/]', '.'", script)
        self.assertNotIn("-replace [\\/], .", script)
