"""Thin Modal CLI runner used by the BAT commands; not part of the server."""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from collections.abc import Sequence

MANIFEST_MODULES = {
    "modal-2d": "modal_2d.deployment",
    "modal-3d": "modal_3d.deployment",
    "modal-world": "modal_world.deployment",
}


def commands(
    action: str, provider: str, app_name: str | None, environment: str | None
) -> list[list[str]]:
    selected = MANIFEST_MODULES if provider == "all" else {provider: MANIFEST_MODULES[provider]}
    targets = []
    for module_name in selected.values():
        manifest = importlib.import_module(module_name).deployment_manifest()
        targets.extend(manifest["targets"])
    if app_name:
        targets = [target for target in targets if target["app"] == app_name]
    if not targets:
        raise ValueError("No matching App in the selected provider manifests")

    result = []
    for target in targets:
        if action == "deploy":
            args = [
                "modal",
                "deploy",
                "-m",
                target["module"],
                "--name",
                target["app"],
                "--strategy",
                "rolling",
            ]
            if target.get("revision"):
                args.extend(["--tag", target["revision"]])
        else:
            args = ["modal", "app", "stop", target["app"], "--yes"]
        if environment:
            args.extend(["--env", environment])
        result.append(args)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deploy or stop manifest-listed Apps. Volumes and Secrets are preserved."
    )
    parser.add_argument("action", choices=["deploy", "stop"])
    parser.add_argument("--provider", choices=["all", *MANIFEST_MODULES])
    parser.add_argument("--app", help="Select one exact App name from the provider manifests")
    parser.add_argument("--env", default=os.environ.get("MODAL_ENVIRONMENT"))
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without cloud access"
    )
    parser.add_argument("--yes", action="store_true", help="Confirm stopping selected cloud Apps")
    args = parser.parse_args(argv)
    if args.action == "stop":
        if not args.provider and not args.app:
            parser.error("Stopping requires an explicit --provider or --app")
        if not args.dry_run and not args.yes:
            parser.error("Stopping cloud Apps requires --yes; inspect --dry-run first")
    try:
        plan = commands(args.action, args.provider or "all", args.app, args.env)
    except ValueError as exc:
        parser.error(str(exc))
    for command in plan:
        print(subprocess.list2cmdline(command), flush=True)
        if not args.dry_run:
            completed = subprocess.run(command, check=False)
            if completed.returncode:
                return completed.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
