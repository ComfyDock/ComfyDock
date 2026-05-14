"""Custom node package identity helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from .git import normalize_github_url

if TYPE_CHECKING:
    from ..models.shared import NodeInfo


def build_installed_node_aliases(
    installed_packages: Mapping[str, NodeInfo],
) -> dict[str, str]:
    """Build exact, unique aliases for installed node package identifiers."""
    aliases: dict[str, str] = {}
    ambiguous: set[str] = set()

    def add(alias: str | None, package_id: str) -> None:
        if not alias:
            return
        existing = aliases.get(alias)
        if existing is not None and existing != package_id:
            ambiguous.add(alias)
            return
        aliases[alias] = package_id

    for package_id, node in installed_packages.items():
        add(package_id, package_id)
        add(node.name, package_id)
        add(node.registry_id, package_id)
        add(node.repository, package_id)

        if node.repository:
            add(normalize_github_url(node.repository), package_id)

    for alias in ambiguous:
        aliases.pop(alias, None)

    return aliases


def resolve_installed_node_alias(
    package_id: str | None,
    installed_packages: Mapping[str, NodeInfo],
    aliases: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve an exact unique alias to an installed manifest package ID."""
    if not package_id:
        return None
    if package_id in installed_packages:
        return package_id

    alias_map = aliases or build_installed_node_aliases(installed_packages)
    resolved = alias_map.get(package_id)
    if resolved and resolved in installed_packages:
        return resolved
    return None
