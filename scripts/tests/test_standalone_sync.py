import importlib.util
import tempfile
import unittest
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "standalone_sync.py"
SPEC = importlib.util.spec_from_file_location("standalone_sync", MODULE_PATH)
standalone_sync = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = standalone_sync
SPEC.loader.exec_module(standalone_sync)


class StandaloneSyncTests(unittest.TestCase):
    def test_modal_world_is_managed_standalone(self):
        spec = standalone_sync.PACKAGES["modal-world"]
        self.assertEqual(spec.branch, "master")
        self.assertEqual(spec.repo, "https://github.com/xiaoqianran/modal-world.git")

    def test_compare_ignores_repository_owned_github_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            target = root / "target"
            (source / ".github" / "workflows").mkdir(parents=True)
            (target / ".github" / "workflows").mkdir(parents=True)
            (source / ".github" / "workflows" / "release.yml").write_text("source")
            (target / ".github" / "workflows" / "release.yml").write_text("standalone")
            (source / "README.md").write_text("same")
            (target / "README.md").write_text("same")

            plan = standalone_sync._compare_trees(source, target)

            self.assertFalse(plan.changed)

    def test_apply_plan_preserves_github_workflow(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            target = root / "target"
            (source / "pkg").mkdir(parents=True)
            (target / "pkg").mkdir(parents=True)
            (target / ".github" / "workflows").mkdir(parents=True)
            (source / "pkg" / "value.txt").write_text("new")
            (target / "pkg" / "value.txt").write_text("old")
            workflow = target / ".github" / "workflows" / "release.yml"
            workflow.write_text("preserve-me")

            plan = standalone_sync._compare_trees(source, target)
            standalone_sync._validate_plan(plan, allow_delete=False)
            standalone_sync._apply_plan(source, target, plan)

            self.assertEqual((target / "pkg" / "value.txt").read_text(), "new")
            self.assertEqual(workflow.read_text(), "preserve-me")

    def test_target_only_file_requires_explicit_delete_permission(self):
        plan = standalone_sync.SyncPlan(added=(), modified=(), deleted=("legacy.txt",))
        with self.assertRaises(RuntimeError):
            standalone_sync._validate_plan(plan, allow_delete=False)
        standalone_sync._validate_plan(plan, allow_delete=True)

    def test_index_mode_matches_canonical_executable_bit(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            standalone_sync._run("git", "init", "-q", str(repo))
            script = repo / "deploy.sh"
            script.write_text("#!/bin/sh\n")
            standalone_sync._run("git", "add", "deploy.sh", cwd=repo)

            standalone_sync._apply_index_modes(repo, {"deploy.sh": "100755"}, ("deploy.sh",))

            entry = standalone_sync._run("git", "ls-files", "-s", "deploy.sh", cwd=repo).stdout
            self.assertTrue(entry.startswith("100755 "), entry)


if __name__ == "__main__":
    unittest.main()
