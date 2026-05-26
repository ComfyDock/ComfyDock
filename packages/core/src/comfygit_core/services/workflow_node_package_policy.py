"""Workflow node package identity policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..utils.git import is_git_url
from ..utils.node_identity import resolve_installed_node_alias

if TYPE_CHECKING:
    from ..managers.pyproject_manager import PyprojectManager
    from ..repositories.node_mappings_repository import NodeMappingsRepository
    from ..resolvers.global_node_resolver import GlobalNodeResolver


class WorkflowNodePackagePolicy:
    """Owns canonical package identity rules for workflow node manifest writes."""

    def __init__(
        self,
        *,
        pyproject: PyprojectManager,
        global_node_resolver: GlobalNodeResolver,
        node_mapping_repository: NodeMappingsRepository,
    ) -> None:
        self.pyproject = pyproject
        self.global_node_resolver = global_node_resolver
        self.node_mapping_repository = node_mapping_repository

    def normalize_package_id(self, package_id: str) -> str:
        """Normalize user-facing or legacy package identifiers for manifest storage."""
        installed_id = resolve_installed_node_alias(
            package_id,
            self.pyproject.nodes.get_existing(),
        )
        if installed_id:
            return installed_id

        if is_git_url(package_id):
            registry_pkg = self.global_node_resolver.resolve_github_url(package_id)
            if registry_pkg:
                return (
                    self.node_mapping_repository.canonicalize_package_id(registry_pkg.id)
                    or registry_pkg.id
                )

        return self.node_mapping_repository.canonicalize_package_id(package_id) or package_id
