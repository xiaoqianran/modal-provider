"""Local Modal deployment control. Shared by BAT wrappers and the HTTP API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from ..credentials import CredentialStore
from ..errors import ConnectorError
from .manifests import MANIFEST_MODULES, load_manifest_adapters
from .service import DeploymentService


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy/stop manifest-approved Modal Apps")
    parser.add_argument("action", choices=("deploy", "stop", "status"))
    parser.add_argument("--provider", choices=("all", *MANIFEST_MODULES))
    parser.add_argument("--app", help="Exact App from a Provider manifest")
    parser.add_argument("--env", default=os.environ.get("MODAL_ENVIRONMENT"))
    parser.add_argument("--yes", action="store_true", help="Confirm stopping App(s)")
    parser.add_argument("--dry-run", action="store_true", help="No Modal API or GPU operations")
    args = parser.parse_args(argv)
    if args.action == "stop":
        if not args.provider and not args.app:
            parser.error("Stopping requires --provider or --app")
        if not args.dry_run and not args.yes:
            parser.error("Stopping requires --yes")
    try:
        service = DeploymentService(load_manifest_adapters())
        targets = service._select_targets(args.provider, args.app)
        if args.dry_run:
            for target in targets:
                print(f"{args.action}: {target.provider} / {target.app_name} ({target.module})")
            return 0
        saved = CredentialStore().load()
        if saved:
            service.connect(saved.token_id, saved.token_secret)
        else:
            import modal

            client = modal.Client.from_env()
            client.hello()
            service._client = client
        if args.action == "deploy":
            result = service.deploy(args.provider, app_name=args.app, environment_name=args.env)
        elif args.action == "stop":
            result = service.stop_apps(args.provider, app_name=args.app, environment_name=args.env)
        else:
            result = service.status(args.provider)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return (
            1
            if any(
                app.get("status") in {"failed", "error"}
                for row in result.get("providers", [])
                for app in row.get("apps", [])
            )
            else 0
        )
    except (ConnectorError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
