"""Static dependency gate plus CPU metadata cross-checks for standard providers."""

import argparse
import ast
import importlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"modal", "torch", "diffusers", "requests", "httpx", "huggingface_hub"}


def check(provider_dir: Path, package: str) -> None:
    root = provider_dir / package
    required = (
        "models/specs.py",
        "models/registry.py",
        "capabilities.py",
        "contracts.py",
        "deployment.py",
        "artifacts.py",
        "client/provider.py",
    )
    for name in required:
        if not (root / name).is_file():
            raise ValueError(f"missing {name}")
    trees = {}
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        module = package + "." + ".".join(relative.with_suffix("").parts)
        module = module.removesuffix(".__init__")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        trees[module] = tree
        layer = relative.parts[0]
        pure = layer in {
            "models",
            "capabilities.py",
            "contracts.py",
            "deployment.py",
            "artifacts.py",
        }
        for node in ast.walk(tree):
            imports = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = (
                        module
                        if path.name == "__init__.py"
                        else module.rsplit(".", 1)[0]
                    )
                    imports = [
                        importlib.util.resolve_name(
                            "." * node.level + (node.module or ""), base
                        )
                    ]
                    imports += [imports[0] + "." + alias.name for alias in node.names]
                else:
                    imports = [node.module or ""]
            for imported in imports:
                parts = imported.split(".")
                local = parts[1:] if parts[0] == package else []
                if pure and (
                    parts[0] in FORBIDDEN
                    or any(
                        part
                        in {"workers", "client", "runtime", "operations", "pipelines"}
                        for part in local
                    )
                ):
                    raise ValueError(
                        f"forbidden metadata dependency: {relative}: {imported}"
                    )
                if layer in {"workers", "runtime"} and (
                    "client" in local or parts[0] in {"modal_gen", "modal_gen_client"}
                ):
                    raise ValueError(
                        f"forbidden Hub/client dependency: {relative}: {imported}"
                    )
    sys.path.insert(0, str(provider_dir.resolve()))
    models = importlib.import_module(package + ".models").list_models()
    registry = importlib.import_module(package + ".models")
    capabilities = importlib.import_module(
        package + ".capabilities"
    ).list_capabilities()
    manifest = importlib.import_module(package + ".deployment").deployment_manifest()
    roles = importlib.import_module(package + ".artifacts").ROLES
    ids = [m.id for m in models]
    if not models or len(ids) != len(set(ids)):
        raise ValueError("empty/duplicate models")
    for model in models:
        if (
            registry.get_model(model.id) != model
            or not model.__dataclass_params__.frozen
        ):
            raise ValueError("invalid immutable registry")
        tree = trees.get(model.worker_module)
        cls = (
            next(
                (
                    n
                    for n in tree.body
                    if isinstance(n, ast.ClassDef) and n.name == model.worker_class
                ),
                None,
            )
            if tree
            else None
        )
        methods = (
            {
                n.name
                for n in cls.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if cls
            else set()
        )
        if not {model.business_method, model.remote_method} <= methods:
            raise ValueError(f"missing worker entrypoint: {model.id}")
    actual = set()
    capability_ids = []
    for capability in capabilities:
        capability_ids.append(capability["id"])
        if not isinstance(capability["contract"], str) or not capability["contract"]:
            raise ValueError("missing contract version")
        for model_id in capability["models"]:
            actual.add((model_id, capability["id"]))
        for output in capability["outputs"]:
            if roles.get(output["role"]) != output["mediaType"]:
                raise ValueError("unknown artifact role/MIME")
    expected = {(m.id, op) for m in models for op in m.operations}
    if actual != expected or len(capability_ids) != len(set(capability_ids)):
        raise ValueError("capability/registry mismatch")
    json.dumps(manifest)
    if (
        manifest.get("schema_version") != 1
        or not isinstance(manifest.get("provider"), str)
        or not manifest["provider"]
    ):
        raise ValueError("invalid manifest header")
    apps, deployed = set(), set()
    targets = manifest["targets"]
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets must be nonempty list")
    for target in targets + manifest.get("utilities", []):
        for field in ("app", "module", "revision"):
            if not isinstance(target[field], str) or not target[field]:
                raise ValueError(f"invalid target {field}")
        if target["app"] in apps or target["module"] not in trees:
            raise ValueError("duplicate app or missing module")
        if target["kind"] not in {"worker", "pipeline", "compiler", "prefetch"}:
            raise ValueError("invalid target kind")
        apps.add(target["app"])
        for field in ("models", "secrets"):
            if not isinstance(target[field], list) or any(
                not isinstance(v, str) or not v for v in target[field]
            ):
                raise ValueError(f"invalid target {field}")
        if not set(target["models"]) <= set(ids):
            raise ValueError("unknown deployment model")
        deployed.update(target["models"])
        if not isinstance(target["weights"], list):
            raise ValueError("weights must be list")
        if target.get("weightless") and target["weights"]:
            raise ValueError("weightless target contains weights")
        for weight in target["weights"]:
            if not isinstance(weight["volume"], str) or not weight["volume"]:
                raise ValueError("invalid weight volume")
            paths = weight["requiredPaths"]
            if not isinstance(paths, list) or any(
                not isinstance(p, str)
                or not p
                or p.startswith("/")
                or ".." in p.split("/")
                or ":" in p
                or "\\" in p
                for p in paths
            ):
                raise ValueError("invalid weight path")
            if not isinstance(weight["prepare"], list):
                raise ValueError("prepare must be list")
            for command in weight["prepare"]:
                if (
                    command["module"] not in trees
                    or not isinstance(command["function"], str)
                    or not command["function"]
                ):
                    raise ValueError("invalid weight preparation entrypoint")
                if not isinstance(command["arguments"], list) or any(
                    not isinstance(v, str) for v in command["arguments"]
                ):
                    raise ValueError("invalid preparation arguments")
    if deployed != set(ids):
        raise ValueError("undeployed registry models")
    for model in models:
        if not any(
            t["app"] == model.worker_app
            and t["module"] == model.worker_module
            and model.id in t["models"]
            for t in targets
        ):
            raise ValueError("worker/deployment mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider-dir", type=Path, default=ROOT / "templates/provider"
    )
    parser.add_argument("--package", default="modal_example")
    args = parser.parse_args()
    try:
        check(args.provider_dir, args.package)
    except (ValueError, KeyError, TypeError, AttributeError, ImportError) as exc:
        print(f"Provider architecture FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"Provider architecture PASS: {args.package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
