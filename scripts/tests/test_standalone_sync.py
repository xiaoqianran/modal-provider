import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "standalone_sync.py"
SPEC = importlib.util.spec_from_file_location("standalone_sync", MODULE_PATH)
standalone_sync = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = standalone_sync
SPEC.loader.exec_module(standalone_sync)


def init_repo(path: Path) -> None:
    standalone_sync._run("git", "init", "-q", str(path))
    standalone_sync._run("git", "config", "user.name", "Standalone Sync Test", cwd=path)
    standalone_sync._run("git", "config", "user.email", "sync-test@example.invalid", cwd=path)


def commit_all(path: Path, message: str = "test") -> None:
    standalone_sync._run("git", "add", "-A", cwd=path)
    standalone_sync._run("git", "commit", "-q", "-m", message, cwd=path)


class StandaloneSyncTests(unittest.TestCase):
    def test_modal_world_is_managed_standalone(self):
        spec = standalone_sync.PACKAGES["modal-world"]
        self.assertEqual(spec.branch, "master")
        self.assertEqual(spec.repo, "https://github.com/xiaoqianran/modal-world.git")

    def test_git_entries_exclude_standalone_github_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            init_repo(repo)
            (repo / ".github" / "workflows").mkdir(parents=True)
            (repo / ".github" / "workflows" / "release.yml").write_text("preserve")
            (repo / "README.md").write_text("tracked")
            commit_all(repo)

            entries = standalone_sync._git_entries(repo)

            self.assertIn("README.md", entries)
            self.assertNotIn(".github/workflows/release.yml", entries)

    def test_compare_entries_detects_mode_changes(self):
        source = {"deploy.sh": standalone_sync.GitEntry("100755", "abc")}
        target = {"deploy.sh": standalone_sync.GitEntry("100644", "abc")}

        plan = standalone_sync._compare_entries(source, target)

        self.assertEqual(plan.modified, ("deploy.sh",))

    def test_target_only_file_requires_explicit_delete_permission(self):
        plan = standalone_sync.SyncPlan(added=(), modified=(), deleted=("legacy.txt",))
        with self.assertRaises(RuntimeError):
            standalone_sync._validate_plan(plan, allow_delete=False)
        standalone_sync._validate_plan(plan, allow_delete=True)

    def test_index_mode_matches_canonical_executable_bit(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            target = Path(temp) / "target"
            init_repo(source)
            init_repo(target)
            (source / "deploy.sh").write_text("#!/bin/sh\n")
            commit_all(source)
            subprocess.run(
                ["git", "update-index", "--chmod=+x", "deploy.sh"],
                cwd=source,
                check=True,
            )
            standalone_sync._run("git", "commit", "-q", "-m", "mode", cwd=source)
            (target / "deploy.sh").write_text("#!/bin/sh\n")
            commit_all(target)

            entries = standalone_sync._git_entries(source)
            standalone_sync._run("git", "add", "-A", cwd=target)
            standalone_sync._apply_index_modes(source, target, entries, ("deploy.sh",))

            entry = standalone_sync._run("git", "ls-files", "-s", "deploy.sh", cwd=target).stdout
            self.assertTrue(entry.startswith("100755 "), entry)

    def test_source_stability_is_scoped_to_package_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            init_repo(repo)
            (repo / "pkg").mkdir()
            (repo / "other").mkdir()
            (repo / "pkg" / "value.txt").write_text("v1")
            (repo / "other" / "value.txt").write_text("v1")
            commit_all(repo, "initial")
            pinned = standalone_sync._package_tree(repo, "pkg", "HEAD")

            (repo / "other" / "value.txt").write_text("v2")
            commit_all(repo, "other-only")
            standalone_sync._assert_source_stable(repo, "pkg", pinned)

            (repo / "pkg" / "value.txt").write_text("v2")
            commit_all(repo, "pkg-change")
            with self.assertRaises(RuntimeError):
                standalone_sync._assert_source_stable(repo, "pkg", pinned)

    def test_source_stability_rejects_mid_sync_dirty_change(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            init_repo(repo)
            (repo / "pkg").mkdir()
            (repo / "pkg" / "value.txt").write_text("v1")
            commit_all(repo)
            pinned = standalone_sync._package_tree(repo, "pkg", "HEAD")
            (repo / "pkg" / "value.txt").write_text("editing")

            with self.assertRaises(RuntimeError):
                standalone_sync._assert_source_stable(repo, "pkg", pinned)


if __name__ == "__main__":
    unittest.main()
