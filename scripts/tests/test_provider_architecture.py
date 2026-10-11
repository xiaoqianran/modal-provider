import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check-provider-architecture.py"


class ProviderArchitectureTests(unittest.TestCase):
    def run_gate(self, provider):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--provider-dir", str(provider)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_reference(self):
        result = self.run_gate(ROOT / "templates/provider")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reject_regressions(self):
        mutations = (
            ("models/specs.py", lambda s: "import modal\n" + s),
            ("models/specs.py", lambda s: "from ..workers import echo\n" + s),
            ("workers/echo.py", lambda s: "from ..client import provider\n" + s),
            (
                "workers/echo.py",
                lambda s: s.replace("def run_job(", "def renamed_job("),
            ),
            (
                "capabilities.py",
                lambda s: s.replace(
                    '"models": [model.id for model in models '
                    'if op in model.operations]',
                    '"models": ["unknown"]',
                ),
            ),
            (
                "capabilities.py",
                lambda s: s.replace('"primary-text"', '"unknown-role"'),
            ),
            (
                "deployment.py",
                lambda s: s.replace(
                    '"module": group[0].worker_module', '"module": "missing.module"'
                ),
            ),
            ("deployment.py", lambda s: s.replace('"secrets": []', '"secrets": "bad"')),
        )
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                provider = Path(directory) / "provider"
                shutil.copytree(
                    ROOT / "templates/provider",
                    provider,
                    ignore=shutil.ignore_patterns(
                        "dist", "build", "*.egg-info", "__pycache__"
                    ),
                )
                path = provider / "modal_example" / name
                path.write_text(
                    mutate(path.read_text(encoding="utf-8")), encoding="utf-8"
                )
                result = self.run_gate(provider)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("FAIL", result.stderr)
