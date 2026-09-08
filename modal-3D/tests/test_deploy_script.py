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
        prepare = script.index('modal run -e main -m "${module}::sync_weights"')
        deploy = script.index("modal deploy -e main -m $module")
        self.assertLess(prepare, deploy)
        self.assertIn("if ($LASTEXITCODE -ne 0)", script[prepare:deploy])

    def test_windows_powershell_51_compatible_relative_path(self) -> None:
        script = (PROJECT_ROOT / "scripts/deploy-worker.ps1").read_text(encoding="utf-8")
        self.assertNotIn("GetRelativePath", script)
        self.assertIn("$workerPath.Substring($repoPrefix.Length)", script)
        self.assertIn("[StringComparison]::OrdinalIgnoreCase", script)

    def test_module_name_removes_extension_without_trailing_dot(self) -> None:
        script = (PROJECT_ROOT / "scripts/deploy-worker.ps1").read_text(encoding="utf-8")
        self.assertNotIn("ChangeExtension", script)
        self.assertIn("$relativePath.Length - $extension.Length", script)
        self.assertIn("$module = $relativeModulePath -replace", script)

    def test_deploy_uses_reproducible_isolated_uv_and_main_environment(self) -> None:
        script = (PROJECT_ROOT / "scripts/deploy-worker.ps1").read_text(encoding="utf-8")
        self.assertIn('"--isolated"', script)
        self.assertIn('"--frozen"', script)
        self.assertIn('"--default-index", "https://pypi.org/simple"', script)
        self.assertEqual(script.count("-e main"), 2)

    def test_modal_cli_is_forced_to_utf8_on_windows(self) -> None:
        script = (PROJECT_ROOT / "scripts/deploy-worker.ps1").read_text(encoding="utf-8")
        self.assertIn('$env:PYTHONUTF8 = "1"', script)
        self.assertIn('$env:PYTHONIOENCODING = "utf-8"', script)

    def test_project_uv_wrappers_use_platform_specific_environments(self) -> None:
        windows = (PROJECT_ROOT / "scripts/uv.ps1").read_text(encoding="utf-8")
        linux = (PROJECT_ROOT / "scripts/uv.sh").read_text(encoding="utf-8")
        self.assertIn('UV_PROJECT_ENVIRONMENT = Join-Path $repoRoot ".venv-windows"', windows)
        self.assertIn('$env:UV_DEFAULT_INDEX = "https://pypi.org/simple"', windows)
        self.assertIn('UV_PROJECT_ENVIRONMENT="${repo_root}/.venv-linux"', linux)
        self.assertIn('UV_DEFAULT_INDEX=https://pypi.org/simple', linux)
        self.assertNotIn('".venv-linux"', windows)
        self.assertNotIn(".venv-windows", linux)

    def test_platform_virtual_environments_are_ignored(self) -> None:
        gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".venv-windows/", gitignore)
        self.assertIn(".venv-linux/", gitignore)

    def test_cross_platform_line_endings_are_pinned(self) -> None:
        attributes = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("uv.lock text eol=lf", attributes)
        self.assertIn("scripts/*.sh text eol=lf", attributes)
        self.assertIn("scripts/*.ps1 text eol=crlf", attributes)

    def test_linux_deploy_matches_windows_reproducibility_contract(self) -> None:
        script = (PROJECT_ROOT / "scripts/deploy-worker.sh").read_text(encoding="utf-8")
        prepare = script.index('modal run -e main -m "${module}::sync_weights"')
        deploy = script.index('modal deploy -e main -m "$module"')
        self.assertLess(prepare, deploy)
        self.assertIn("--isolated", script)
        self.assertIn("--frozen", script)
        self.assertIn("--default-index https://pypi.org/simple", script)
