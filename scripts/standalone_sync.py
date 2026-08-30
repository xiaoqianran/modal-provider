#!/usr/bin/env python3
"""Safe synchronization between modal-provider packages and standalone repositories."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PackageSpec:
    repo: str
    branch: str


PACKAGES: dict[str, PackageSpec] = {
    "modal-2D": PackageSpec("https://github.com/xiaoqianran/modal-2D.git", "main"),
    "modal-2D-client": PackageSpec("https://github.com/xiaoqianran/modal-2D-client.git", "main"),
    "modal-3D": PackageSpec("https://github.com/xiaoqianran/modal-3D.git", "master"),
    "modal-3D-client": PackageSpec("https://github.com/xiaoqianran/modal-3D-client.git", "main"),
    "modal-gen-client": PackageSpec("https://github.com/xiaoqianran/modal-gen-client.git", "main"),
    "modal-EmbodiedGen": PackageSpec("https://github.com/xiaoqianran/modal-EmbodiedGen.git", "master"),
    "modal-build": PackageSpec("https://github.com/xiaoqianran/modal-build.git", "master"),
    "modal-world": PackageSpec("https://github.com/xiaoqianran/modal-world.git", "master"),
}

PROTECTED_TOP_LEVEL = frozenset({".git", ".github"})
IGNORED_NAMES = frozenset(
    {
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "build",
        "dist",
        "coverage",
    }
)


@dataclass(frozen=True)
class SyncPlan:
    added: tuple[str, ...]
    modified: tuple[str, ...]
    deleted: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.modified or self.deleted)


def _run(
    *args: str,
    cwd: Path | None = None,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )


def _repo_root() -> Path:
    result = _run("git", "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve()


def _is_ignored(relative: Path) -> bool:
    if not relative.parts:
        return False
    if relative.parts[0] in PROTECTED_TOP_LEVEL:
        return True
    return any(part in IGNORED_NAMES or part.endswith(".egg-info") for part in relative.parts)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _is_ignored(relative):
            continue
        files[relative.as_posix()] = _digest(path)
    return files


def _compare_trees(source: Path, target: Path) -> SyncPlan:
    source_files = _manifest(source)
    target_files = _manifest(target)
    source_names = set(source_files)
    target_names = set(target_files)
    return SyncPlan(
        added=tuple(sorted(source_names - target_names)),
        modified=tuple(
            sorted(
                name
                for name in source_names & target_names
                if source_files[name] != target_files[name]
            )
        ),
        deleted=tuple(sorted(target_names - source_names)),
    )


def _print_plan(package: str, plan: SyncPlan) -> None:
    if not plan.changed:
        print(f"SYNC    {package:<20} no source drift")
        return
    print(
        f"DRIFT   {package:<20} +{len(plan.added)} "
        f"~{len(plan.modified)} -{len(plan.deleted)}"
    )
    for marker, paths in (("+", plan.added), ("~", plan.modified), ("-", plan.deleted)):
        for path in paths[:80]:
            print(f"  {marker} {path}")
        if len(paths) > 80:
            print(f"  ... {len(paths) - 80} more {marker} entries")


def _validate_plan(plan: SyncPlan, allow_delete: bool) -> None:
    if plan.deleted and not allow_delete:
        names = ", ".join(plan.deleted[:5])
        more = " ..." if len(plan.deleted) > 5 else ""
        raise RuntimeError(
            "standalone-only files would be deleted; review the dry-run and rerun with "
            f"--allow-delete only when intended: {names}{more}"
        )


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _apply_plan(source: Path, target: Path, plan: SyncPlan) -> None:
    for relative in plan.deleted:
        path = target / relative
        if path.exists():
            path.unlink()
    for relative in (*plan.added, *plan.modified):
        _copy_file(source / relative, target / relative)

    for directory in sorted(
        (path for path in target.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        relative = directory.relative_to(target)
        if _is_ignored(relative):
            continue
        try:
            directory.rmdir()
        except OSError:
            pass


def _assert_source_clean(root: Path, package: str) -> None:
    result = _run(
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        package,
        cwd=root,
    )
    if result.stdout.strip():
        raise RuntimeError(
            f"{package} has uncommitted source changes; commit or stash them before standalone sync"
        )


def _source_modes(root: Path, package: str) -> dict[str, str]:
    result = _run("git", "ls-tree", "-r", "HEAD", "--", package, cwd=root)
    prefix = f"{package}/"
    modes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        metadata, path = line.split("\t", 1)
        mode, _kind, _object_id = metadata.split()
        if path.startswith(prefix):
            modes[path[len(prefix) :]] = mode
    return modes


def _apply_index_modes(target: Path, source_modes: dict[str, str], paths: tuple[str, ...]) -> None:
    for relative in paths:
        mode = source_modes.get(relative)
        if mode == "100755":
            _run("git", "update-index", "--chmod=+x", "--", relative, cwd=target)
        elif mode == "100644":
            _run("git", "update-index", "--chmod=-x", "--", relative, cwd=target)
        else:
            raise RuntimeError(
                f"refusing sync for unsupported or untracked source mode: {relative} ({mode})"
            )


def _clone(spec: PackageSpec, destination: Path) -> None:
    _run(
        "git",
        "clone",
        "--quiet",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        spec.branch,
        spec.repo,
        str(destination),
    )


def _assert_protected_unchanged(target: Path) -> None:
    result = _run("git", "status", "--porcelain=v1", "--", ".github", cwd=target)
    if result.stdout.strip():
        raise RuntimeError("refusing sync: standalone .github changed")


def _check(package: str, root: Path) -> bool:
    spec = PACKAGES[package]
    source = root / package
    if not source.is_dir():
        raise RuntimeError(f"missing package directory: {source}")
    with tempfile.TemporaryDirectory(prefix=f"{package}-check-") as temp:
        target = Path(temp) / package
        _clone(spec, target)
        plan = _compare_trees(source, target)
        _print_plan(package, plan)
        return not plan.changed


def _sync(
    package: str,
    root: Path,
    *,
    push: bool,
    allow_delete: bool,
    message: str | None,
) -> None:
    spec = PACKAGES[package]
    source = root / package
    if not source.is_dir():
        raise RuntimeError(f"missing package directory: {source}")
    _assert_source_clean(root, package)

    with tempfile.TemporaryDirectory(prefix=f"{package}-sync-") as temp:
        target = Path(temp) / package
        _clone(spec, target)
        plan = _compare_trees(source, target)
        _print_plan(package, plan)
        if not plan.changed:
            return
        _validate_plan(plan, allow_delete)

        if not push:
            print("DRY-RUN no files changed; add --push to commit and fast-forward push")
            return

        _apply_plan(source, target, plan)
        _assert_protected_unchanged(target)
        _run("git", "diff", "--check", cwd=target)
        _run("git", "add", "-A", "--", ".", cwd=target)
        source_modes = _source_modes(root, package)
        _apply_index_modes(target, source_modes, (*plan.added, *plan.modified))
        _assert_protected_unchanged(target)

        commit_message = message or f"chore(sync): sync {package} from modal-provider"
        _run("git", "commit", "-m", commit_message, cwd=target, capture=False)
        local_head = _run("git", "rev-parse", "HEAD", cwd=target).stdout.strip()
        _run(
            "git",
            "push",
            "origin",
            f"HEAD:refs/heads/{spec.branch}",
            cwd=target,
            capture=False,
        )
        remote_line = _run(
            "git",
            "ls-remote",
            "origin",
            f"refs/heads/{spec.branch}",
            cwd=target,
        ).stdout.strip()
        remote_head = remote_line.split()[0] if remote_line else ""
        if remote_head != local_head:
            raise RuntimeError(
                f"push verification failed: local={local_head} remote={remote_head or '<missing>'}"
            )
        print(f"PUSHED  {package:<20} {spec.branch} {local_head[:12]}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check or safely sync modal-provider packages to standalone repositories. "
            "The sync path never copies .git/.github, never force-pushes, and never touches tags or Releases."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="compare canonical package source with standalone")
    check.add_argument("packages", nargs="*", choices=sorted(PACKAGES))

    sync = subparsers.add_parser("sync", help="dry-run or safely sync one standalone repository")
    sync.add_argument("package", choices=sorted(PACKAGES))
    sync.add_argument("--push", action="store_true", help="commit and normal fast-forward push")
    sync.add_argument(
        "--allow-delete",
        action="store_true",
        help="allow deletion of reviewed standalone-only non-protected files",
    )
    sync.add_argument("--message", help="override the generated commit message")

    subparsers.add_parser("list", help="list managed standalone repositories")
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = _repo_root()
    try:
        if args.command == "list":
            for package, spec in PACKAGES.items():
                print(f"{package:<20} {spec.branch:<6} {spec.repo}")
            return 0
        if args.command == "check":
            packages = args.packages or list(PACKAGES)
            results = [_check(package, root) for package in packages]
            return 0 if all(results) else 1
        if args.command == "sync":
            _sync(
                args.package,
                root,
                push=args.push,
                allow_delete=args.allow_delete,
                message=args.message,
            )
            return 0
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR   {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
