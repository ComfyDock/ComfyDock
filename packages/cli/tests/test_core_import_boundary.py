"""Guard CLI imports against accidental coupling to core internals."""

from __future__ import annotations

import ast
from pathlib import Path

PUBLIC_CORE_IMPORTS = {
    "comfygit_core",
    "comfygit_core.assets",
    "comfygit_core.git",
    "comfygit_core.models",
    "comfygit_core.readiness",
    "comfygit_core.runtime",
    "comfygit_core.workflow",
}

TEMPORARY_INTERNAL_IMPORTS = {
    # TODO: move interactive/auto strategy ownership behind CLI-owned strategies
    # and Environment.resolve_workflow(mode=\"auto\").
    "comfygit_core.strategies.auto",
    "comfygit_core.strategies.confirmation",
    # TODO: expose torch backend probing through Environment facade methods.
    "comfygit_core.utils.pytorch_prober",
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


def test_cli_runtime_uses_public_core_facades_or_temporary_allowlist():
    cli_root = Path(__file__).resolve().parents[1] / "comfygit_cli"
    violations: list[str] = []

    for path in sorted(cli_root.rglob("*.py")):
        for module, line in _core_imports(path):
            if module in PUBLIC_CORE_IMPORTS or module in TEMPORARY_INTERNAL_IMPORTS:
                continue
            violations.append(f"{path.relative_to(cli_root.parent)}:{line}: {module}")

    assert not violations, "CLI imported unsupported core internals:\n" + "\n".join(violations)
