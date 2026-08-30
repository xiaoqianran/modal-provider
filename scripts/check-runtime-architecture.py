from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIRS = (
    ROOT / "modal-2D-client" / "modal_2d_client",
    ROOT / "modal-3D-client" / "modal_3d_client",
)


def dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def python_files(root: Path):
    yield from sorted(root.rglob("*.py"))


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def check_client_calls(failures: list[str]) -> None:
    cls_lookups: dict[str, int] = {
        str(root.relative_to(ROOT)): 0 for root in CLIENT_DIRS
    }
    for root in CLIENT_DIRS:
        key = str(root.relative_to(ROOT))
        for path in python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = dotted_name(node.func)
                if name == "modal.Function.from_name":
                    fail(
                        f"{path.relative_to(ROOT)}:{node.lineno}: remote CPU Function lookup is forbidden; use direct GPU Cls.from_name",
                        failures,
                    )
                elif name == "modal.Cls.from_name":
                    cls_lookups[key] += 1
    for root, count in cls_lookups.items():
        if count == 0:
            fail(f"{root}: no direct modal.Cls.from_name worker lookup found", failures)


def check_2d_control_plane(failures: list[str]) -> None:
    package = ROOT / "modal-2D" / "modal_2d"
    forbidden_contract_tokens = (
        "control_app",
        "artifact_function",
        "CAPABILITIES_FUNCTION",
        "ARTIFACT_FUNCTION",
    )
    for path in python_files(package):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_contract_tokens:
            if token in text:
                fail(
                    f"{path.relative_to(ROOT)}: legacy 2D CPU gateway token {token!r} is forbidden",
                    failures,
                )

    app_path = package / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"), filename=str(app_path))
    remote_functions: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if dotted_name(target) == "app.function":
                remote_functions.append(node.name)
    unexpected = sorted(set(remote_functions) - {"prefetch"})
    if unexpected:
        fail(
            f"{app_path.relative_to(ROOT)}: only optional prefetch may be a 2D control-plane @app.function; found {unexpected}",
            failures,
        )


def main() -> int:
    failures: list[str] = []
    check_client_calls(failures)
    check_2d_control_plane(failures)
    if failures:
        print("Runtime architecture gate FAILED", file=sys.stderr)
        for item in failures:
            print(f"- {item}", file=sys.stderr)
        return 1
    print(
        "Runtime architecture gate passed: 2D/3D clients use direct worker class lookup; 2D CPU gateway = 0."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
