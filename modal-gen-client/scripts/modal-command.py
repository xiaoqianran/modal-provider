"""Compatibility wrapper: use modal_gen.deployment.cli as the implementation."""

from modal_gen.deployment.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
