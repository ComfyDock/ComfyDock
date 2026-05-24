"""Dependency-group helpers for pyproject manifests."""
from __future__ import annotations

from ..logging.logging_config import get_logger
from ..utils.dependency_parser import parse_dependency_string
from .base import BaseHandler

logger = get_logger(__name__)


class DependencyHandler(BaseHandler):
    """Handles dependency groups and analysis."""

    def get_groups(self) -> dict[str, list[str]]:
        """Get all dependency groups."""
        try:
            config = self.load()
            return config.get('dependency-groups', {})
        except Exception:
            return {}

    def add_to_group(self, group: str, packages: list[str]) -> None:
        """Add packages to a dependency group."""
        config = self.load()

        if 'dependency-groups' not in config:
            config['dependency-groups'] = {}

        if group not in config['dependency-groups']:
            config['dependency-groups'][group] = []

        group_deps = config['dependency-groups'][group]
        added_count = 0

        for pkg in packages:
            if pkg not in group_deps:
                group_deps.append(pkg)
                added_count += 1

        logger.info(f"Added {added_count} packages to group '{group}'")
        self.save(config)

    def remove_group(self, group: str) -> None:
        """Remove a dependency group."""
        config = self.load()

        if 'dependency-groups' not in config:
            raise ValueError("No dependency groups found")

        if group not in config['dependency-groups']:
            raise ValueError(f"Group '{group}' not found")

        del config['dependency-groups'][group]
        logger.info(f"Removed dependency group: {group}")
        self.save(config)

    def remove_from_group(self, group: str, packages: list[str]) -> dict[str, list[str]]:
        """Remove specific packages from a dependency group.

        Matches packages case-insensitively by extracting package names from
        dependency specifications (e.g., "pillow>=9.0.0" matches "pillow").

        Args:
            group: Dependency group name
            packages: List of package names to remove (without version specs)

        Returns:
            Dict with 'removed' (list of packages removed) and 'skipped' (list not found)

        Raises:
            ValueError: If group doesn't exist
        """
        config = self.load()

        if 'dependency-groups' not in config:
            raise ValueError("No dependency groups found")

        if group not in config['dependency-groups']:
            raise ValueError(f"Group '{group}' not found")

        group_deps = config['dependency-groups'][group]

        # Normalize package names for case-insensitive comparison
        packages_to_remove = {pkg.lower() for pkg in packages}

        # Track what we remove and skip
        removed = []
        remaining = []

        for dep in group_deps:
            pkg_name, _ = parse_dependency_string(dep)
            if pkg_name.lower() in packages_to_remove:
                removed.append(pkg_name)
            else:
                remaining.append(dep)

        # Update or delete the group
        if remaining:
            config['dependency-groups'][group] = remaining
        else:
            # If no packages left, delete the entire group
            del config['dependency-groups'][group]
            logger.info(f"Removed empty dependency group: {group}")

        # Find skipped packages (requested but not found)
        removed_lower = {pkg.lower() for pkg in removed}
        skipped = [pkg for pkg in packages if pkg.lower() not in removed_lower]

        if removed:
            logger.info(f"Removed {len(removed)} package(s) from group '{group}'")

        self.save(config)

        return {
            'removed': removed,
            'skipped': skipped
        }
