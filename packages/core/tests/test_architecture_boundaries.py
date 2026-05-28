"""Architecture guardrails for core package boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


def _called_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_core_runtime_code_does_not_prompt_or_print_directly():
    """Core should return data/log events and let adapters own user interaction."""
    core_root = Path(__file__).resolve().parents[1] / "src" / "comfygit_core"
    violations: list[str] = []

    for path in sorted(core_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _called_name(node.func) in {"input", "print"}:
                violations.append(f"{path.relative_to(core_root)}:{node.lineno}")

    assert not violations, "Core runtime code directly prompts or prints:\n" + "\n".join(violations)
