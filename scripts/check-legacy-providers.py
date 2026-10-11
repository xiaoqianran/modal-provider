"""Legacy Provider compatibility gate; static only, no GPU imports or model downloads."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {
    "modal-2D": "modal_2d",
    "modal-3D": "modal_3d",
    "modal-world": "modal_world",
}
FORBIDDEN_HUB = {"modal_gen", "modal_gen_client"}


def inspect_provider(folder: Path, package: str) -> list[str]:
    """Validate existing public seams without enforcing the new directory layout."""
    failures: list[str] = []
    base = folder / package
    required = ("deployment.py", "capabilities.py" if package != "modal_world" else "registry.py")
    if not ((base / "contracts.py").is_file() or (base / "client" / "contracts.py").is_file()):
        failures.append(f"{package}: missing public contracts")
    for required_file in required:
        if not (base / required_file).is_file():
            failures.append(f"{package}: missing {required_file}")
    manifest = base / "deployment.py"
    if manifest.is_file():
        tree = ast.parse(manifest.read_text(encoding="utf-8"), filename=str(manifest))
        functions = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if "deployment_manifest" not in functions:
            failures.append(f"{package}: missing deployment_manifest()")
    entrypoint = folder / "pyproject.toml"
    if entrypoint.is_file():
        import tomllib
        meta = tomllib.loads(entrypoint.read_text(encoding="utf-8"))
        providers = meta.get("project", {}).get("entry-points", {}).get("modal_gen.providers", {})
        if not providers:
            failures.append(f"{package}: no Hub entry point")
        for target in providers.values():
            module = target.partition(":")[0]
            if not module.startswith(package + "."):
                failures.append(f"{package}: foreign entry point {target}")
            elif not (base / (module[len(package)+1:].replace(".", "/") + ".py")).is_file():
                failures.append(f"{package}: missing entry point module {module}")
    else:
        failures.append(f"{package}: missing pyproject.toml")
    for path in sorted(base.rglob("*.py")):
        rel = path.relative_to(base)
        # Model code must not import the product Hub or its local client.
        # Existing Provider adapters under client/ are intentionally exempt.
        if "client" in rel.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] if node.level == 0 else []
                # Relative import of own client must also be disallowed in model/runtime code.
                if node.level and node.module and node.module.split(".")[0] == "client":
                    failures.append(f"{package}/{rel}: imports local client")
            else:
                continue
            if any(name.split(".")[0] in FORBIDDEN_HUB for name in names):
                failures.append(f"{package}/{rel}: imports Hub")
    return failures


def main() -> int:
    failures = [error for folder, package in PROVIDERS.items()
                for error in inspect_provider(ROOT / folder, package)]
    if failures:
        for error in failures:
            print("FAIL:", error)
        return 1
    print("Legacy Provider architecture PASS: " + ", ".join(PROVIDERS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

