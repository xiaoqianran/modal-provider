from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DeployScriptTests(unittest.TestCase):
    def test_powershell_module_replacement_is_quoted(self) -> None:
        script = (PROJECT_ROOT / "scripts/deploy-worker.ps1").read_text(encoding="utf-8")
        self.assertIn("-replace '[\\\\/]', '.'", script)
        self.assertNotIn("-replace [\\/], .", script)

    def test_weights_are_prepared_before_deployment(self) -> None:
        script = (PROJECT_ROOT / "scripts/deploy-worker.ps1").read_text(encoding="utf-8")
        prepare = script.index('uv run modal run -m "${module}::sync_weights"')
        deploy = script.index("uv run modal deploy -m $module")
        self.assertLess(prepare, deploy)
        self.assertIn("if ($LASTEXITCODE -ne 0)", script[prepare:deploy])
