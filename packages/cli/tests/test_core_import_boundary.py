"""Guard CLI imports against accidental coupling to core internals."""

from __future__ import annotations

import ast
from pathlib import Path

PUBLIC_CORE_IMPORTS = {
    "comfygit_core",
    "comfygit_core.assets",
    "comfygit_core.confirmation",
    "comfygit_core.git",
    "comfygit_core.models",
    "comfygit_core.readiness",
    "comfygit_core.runtime",
    "comfygit_core.workflow",
}

DISALLOWED_ENV_REACH_THROUGH_ATTRS = {
    "git_manager",
    "model_manager",
    "node_manager",
    "overlay_manager",
    "pyproject",
    "pytorch_manager",
    "uv_manager",
    "workflow_manager",
}


def _core_imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "comfygit_core" or alias.name.startswith("comfygit_core."):
                    imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "comfygit_core" or module.startswith("comfygit_core."):
                imports.append((module, node.lineno))
    return imports


def _assert_tree_uses_public_core_facades(root: Path, label: str) -> None:
    violations: list[str] = []

    for path in sorted(root.rglob("*.py")):
        for module, line in _core_imports(path):
            if module in PUBLIC_CORE_IMPORTS:
                continue
            violations.append(f"{path.relative_to(root.parent)}:{line}: {module}")

    assert not violations, f"{label} imported unsupported core internals:\n" + "\n".join(violations)


def test_cli_runtime_uses_public_core_facades_or_temporary_allowlist():
    cli_root = Path(__file__).resolve().parents[1] / "comfygit_cli"
    _assert_tree_uses_public_core_facades(cli_root, "CLI runtime")


def test_cli_tests_use_public_core_facades_or_explicit_public_models():
    tests_root = Path(__file__).resolve().parent
    _assert_tree_uses_public_core_facades(tests_root, "CLI tests")


def test_env_commands_use_environment_facades_instead_of_manager_reach_throughs():
    path = Path(__file__).resolve().parents[1] / "comfygit_cli" / "env_commands.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "env"
            and node.attr in DISALLOWED_ENV_REACH_THROUGH_ATTRS
        ):
            violations.append(f"{path.name}:{node.lineno}: env.{node.attr}")

    assert not violations, "env_commands reached through Environment facade:\n" + "\n".join(violations)


def test_cli_config_commands_use_workspace_facades_instead_of_config_repository():
    path = Path(__file__).resolve().parents[1] / "comfygit_cli" / "global_commands.py"
    source = path.read_text(encoding="utf-8")

    assert "workspace_config_manager" not in source
