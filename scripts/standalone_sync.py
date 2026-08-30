#!/usr/bin/env python3
"""Safe synchronization between modal-provider packages and standalone repositories."""

from __future__ import annotations

import argparse
import os
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


@dataclass(frozen=True)
class GitEntry:
    mode: str
    oid: str


@dataclass(frozen=True)
class SyncPlan:
    added: tuple[str, ...]
    modified: tuple[str, ...]
    deleted: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    @property
    def paths(self) -> tuple[str, ...]:
        return (*self.added, *self.modified, *self.deleted)


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
SUPPORTED_BLOB_MODES = frozenset({"100644", "100755", "120000"})


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


def _run_bytes(*args: str, cwd: Path) -> bytes:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def _repo_root() -> Path:
    result = _run("git", "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve()


def _source_status(root: Path, package: str) -> str:
    return _run(
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        package,
        cwd=root,
    ).stdout.strip()


def _assert_source_clean(root: Path, package: str) -> None:
    status = _source_status(root, package)
    if status:
        raise RuntimeError(
            f"{package} has uncommitted source changes; commit or stash them before standalone sync"
        )


def _revision(root: Path) -> str:
    return _run("git", "rev-parse", "HEAD", cwd=root).stdout.strip()


def _package_tree(root: Path, package: str, revision: str) -> str:
    return _run("git", "rev-parse", f"{revision}:{package}", cwd=root).stdout.strip()


def _assert_source_stable(root: Path, package: str, pinned_tree: str) -> None:
    _assert_source_clean(root, package)
    current_tree = _package_tree(root, package, "HEAD")
    if current_tree != pinned_tree:
        raise RuntimeError(
            f"{package} changed while sync was running; refusing stale push, rerun from the new canonical HEAD"
        )


def _git_entries(repo: Path, revision: str = "HEAD", prefix: str | None = None) -> dict[str, GitEntry]:
    args = ["git", "ls-tree", "-r", revision]
    if prefix:
        args.extend(["--", prefix])
    result = _run(*args, cwd=repo)
    entries: dict[str, GitEntry] = {}
    prefix_text = f"{prefix}/" if prefix else ""

    for line in result.stdout.splitlines():
        metadata, path = line.split("\t", 1)
        mode, kind, oid = metadata.split()
        if kind not in {"blob", "commit"}:
            raise RuntimeError(f"unsupported git tree entry kind {kind}: {path}")
        if prefix:
            if not path.startswith(prefix_text):
                continue
            path = path[len(prefix_text) :]
        relative = Path(path)
        if relative.parts and relative.parts[0] in PROTECTED_TOP_LEVEL:
            continue
        entries[relative.as_posix()] = GitEntry(mode=mode, oid=oid)
    return entries


def _compare_entries(source: dict[str, GitEntry], target: dict[str, GitEntry]) -> SyncPlan:
    source_names = set(source)
    target_names = set(target)
    return SyncPlan(
        added=tuple(sorted(source_names - target_names)),
        modified=tuple(
            sorted(name for name in source_names & target_names if source[name] != target[name])
        ),
        deleted=tuple(sorted(target_names - source_names)),
    )


def _print_plan(package: str, plan: SyncPlan, revision: str) -> None:
    short_revision = revision[:12]
    if not plan.changed:
        print(f"SYNC    {package:<20} source={short_revision} no committed drift")
        return
    print(
        f"DRIFT   {package:<20} source={short_revision} "
        f"+{len(plan.added)} ~{len(plan.modified)} -{len(plan.deleted)}"
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


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _read_blob(source_repo: Path, entry: GitEntry) -> bytes:
    if entry.mode not in SUPPORTED_BLOB_MODES:
        raise RuntimeError(f"unsupported git mode for standalone sync: {entry.mode}")
    return _run_bytes("git", "cat-file", "blob", entry.oid, cwd=source_repo)


def _write_entry(source_repo: Path, target: Path, relative: str, entry: GitEntry) -> None:
    path = target / relative
    _remove_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = _read_blob(source_repo, entry)

    if entry.mode == "120000":
        link_target = blob.decode("utf-8")
        try:
            os.symlink(link_target, path)
        except (OSError, NotImplementedError):
            path.write_bytes(blob)
        return

    path.write_bytes(blob)
    try:
        path.chmod(0o755 if entry.mode == "100755" else 0o644)
    except OSError:
        pass


def _prune_empty_parents(target: Path, relative: str) -> None:
    directory = (target / relative).parent
    while directory != target:
        if directory.name in PROTECTED_TOP_LEVEL:
            return
        try:
            directory.rmdir()
        except OSError:
            return
        directory = directory.parent


def _apply_plan(
    source_repo: Path,
    source_entries: dict[str, GitEntry],
    target: Path,
    plan: SyncPlan,
) -> None:
    for relative in plan.deleted:
        _remove_path(target / relative)
        _prune_empty_parents(target, relative)
    for relative in (*plan.added, *plan.modified):
        _write_entry(source_repo, target, relative, source_entries[relative])


def _apply_index_modes(
    source_repo: Path,
    target: Path,
    source_entries: dict[str, GitEntry],
    paths: tuple[str, ...],
) -> None:
    for relative in paths:
        entry = source_entries[relative]
        if entry.mode == "100755":
            _run("git", "update-index", "--chmod=+x", "--", relative, cwd=target)
        elif entry.mode == "100644":
            _run("git", "update-index", "--chmod=-x", "--", relative, cwd=target)
        elif entry.mode == "120000":
            blob = _read_blob(source_repo, entry)
            hashed = subprocess.run(
                ["git", "hash-object", "-w", "--stdin"],
                cwd=target,
                check=True,
                input=blob,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout.decode().strip()
            if hashed != entry.oid:
                raise RuntimeError(f"blob verification failed for symlink: {relative}")
            _run(
                "git",
                "update-index",
                "--add",
                "--cacheinfo",
                f"120000,{entry.oid},{relative}",
                cwd=target,
            )
        else:
            raise RuntimeError(f"unsupported git mode for standalone sync: {entry.mode} {relative}")


def _assert_protected_unchanged(target: Path) -> None:
    result = _run("git", "status", "--porcelain=v1", "--", ".github", cwd=target)
    if result.stdout.strip():
        raise RuntimeError("refusing sync: standalone .github changed")


def _assert_staged_paths(target: Path, plan: SyncPlan) -> None:
    staged = {
        line.strip()
        for line in _run("git", "diff", "--cached", "--name-only", cwd=target).stdout.splitlines()
        if line.strip()
    }
    expected = set(plan.paths)
    if staged != expected:
        raise RuntimeError(
            f"refusing sync: staged path set differs from reviewed plan; expected={sorted(expected)} "
            f"actual={sorted(staged)}"
        )


def _check(package: str, root: Path) -> bool:
    spec = PACKAGES[package]
    if not (root / package).is_dir():
        raise RuntimeError(f"missing package directory: {root / package}")

    source_revision = _revision(root)
    source_entries = _git_entries(root, source_revision, package)
    dirty = _source_status(root, package)
    if dirty:
        print(f"DIRTY   {package:<20} local source has uncommitted changes; comparing committed HEAD only")

    with tempfile.TemporaryDirectory(prefix=f"{package}-check-") as temp:
        target = Path(temp) / package
        _clone(spec, target)
        target_entries = _git_entries(target)
        plan = _compare_entries(source_entries, target_entries)
        _print_plan(package, plan, source_revision)
        return not plan.changed and not dirty


def _sync(
    package: str,
    root: Path,
    *,
    push: bool,
    allow_delete: bool,
    message: str | None,
) -> None:
    spec = PACKAGES[package]
    if not (root / package).is_dir():
        raise RuntimeError(f"missing package directory: {root / package}")

    _assert_source_clean(root, package)
    source_revision = _revision(root)
    pinned_tree = _package_tree(root, package, source_revision)
    source_entries = _git_entries(root, source_revision, package)

    with tempfile.TemporaryDirectory(prefix=f"{package}-sync-") as temp:
        target = Path(temp) / package
        _clone(spec, target)
        target_entries = _git_entries(target)
        plan = _compare_entries(source_entries, target_entries)
        _print_plan(package, plan, source_revision)
        _assert_source_stable(root, package, pinned_tree)
        if not plan.changed:
            return
        _validate_plan(plan, allow_delete)

        if not push:
            print("DRY-RUN no files changed; add --push to commit and fast-forward push")
            return

        _apply_plan(root, source_entries, target, plan)
        _assert_protected_unchanged(target)
        _run("git", "diff", "--check", cwd=target)
        _run("git", "add", "-A", "--", ".", cwd=target)
        _apply_index_modes(root, target, source_entries, (*plan.added, *plan.modified))
        _assert_protected_unchanged(target)
        _assert_staged_paths(target, plan)
        _assert_source_stable(root, package, pinned_tree)

        commit_message = message or f"chore(sync): sync {package} from modal-provider"
        _run("git", "commit", "-m", commit_message, cwd=target, capture=False)
        local_head = _run("git", "rev-parse", "HEAD", cwd=target).stdout.strip()
        _assert_source_stable(root, package, pinned_tree)
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
        _assert_source_stable(root, package, pinned_tree)
        print(
            f"PUSHED  {package:<20} {spec.branch} {local_head[:12]} "
            f"source={source_revision[:12]}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check or safely sync committed modal-provider package source to standalone repositories. "
            "The sync path never copies .git/.github, never force-pushes, and never touches tags or Releases."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="compare committed canonical package source with standalone")
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
    except (RuntimeError, subprocess.CalledProcessError, UnicodeDecodeError) as exc:
        print(f"ERROR   {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
