"""UV configuration helpers for pyproject manifests."""
from __future__ import annotations

import tomlkit

from ..logging.logging_config import get_logger
from ..utils.dependency_parser import parse_dependency_string
from .base import BaseHandler

logger = get_logger(__name__)


class UVConfigHandler(BaseHandler):
    """Handles UV-specific configuration."""

    # System-level sources that should never be auto-removed
    PROTECTED_SOURCES = {'pytorch-cuda', 'pytorch-cpu', 'torch-cpu', 'torch-cuda'}

    def add_constraint(self, package: str) -> None:
        """Add a constraint dependency to [tool.uv]."""
        config = self.load()
        self.ensure_section(config, 'tool', 'uv')

        constraints = config['tool']['uv'].get('constraint-dependencies', [])

        # Extract package name for comparison
        pkg_name = self._extract_package_name(package)

        # Update existing or add new
        for i, existing in enumerate(constraints):
            if self._extract_package_name(existing) == pkg_name:
                logger.info(f"Updating constraint: {existing} -> {package}")
                constraints[i] = package
                break
        else:
            logger.info(f"Adding constraint: {package}")
            constraints.append(package)

        config['tool']['uv']['constraint-dependencies'] = constraints
        self.save(config)

    def add_no_build_isolation_package(self, package_name: str) -> None:
        """Add package to no-build-isolation-package list."""
        config = self.load()
        self.ensure_section(config, 'tool', 'uv')

        packages = config['tool']['uv'].get('no-build-isolation-package', [])
        if not isinstance(packages, list):
            packages = [packages] if packages else []

        normalized = package_name.lower().replace('_', '-')
        existing = {p.lower().replace('_', '-') for p in packages}

        if normalized not in existing:
            packages.append(normalized)
            config['tool']['uv']['no-build-isolation-package'] = packages
            self.save(config)
            logger.info(f"Added no-build-isolation package: {normalized}")

    def remove_constraint(self, package_name: str) -> bool:
        """Remove a constraint dependency from [tool.uv]."""
        config = self.load()
        constraints = config.get('tool', {}).get('uv', {}).get('constraint-dependencies', [])

        if not constraints:
            return False

        target_package = self._extract_package_name(package_name)

        # Find and remove constraint by package name
        for i, existing in enumerate(constraints):
            if self._extract_package_name(existing) == target_package:
                removed = constraints.pop(i)
                logger.info(f"Removing constraint: {removed}")
                config['tool']['uv']['constraint-dependencies'] = constraints
                self.save(config)
                return True

        return False

    def add_index(self, name: str, url: str, explicit: bool = True) -> None:
        """Add an index to [[tool.uv.index]].

        Always produces array-of-tables format to match uv's formatting.
        """
        config = self.load()
        self.ensure_section(config, 'tool', 'uv')
        indexes = config['tool']['uv'].get('index', [])

        if not isinstance(indexes, list):
            indexes = [indexes] if indexes else []

        # Create new table entry for the index
        new_entry = tomlkit.table()
        new_entry['name'] = name
        new_entry['url'] = url
        new_entry['explicit'] = explicit

        # Update existing or add new
        updated = False
        for i, existing in enumerate(indexes):
            if existing.get('name') == name:
                logger.info(f"Updating index '{name}'")
                indexes[i] = new_entry
                updated = True
                break

        if not updated:
            logger.info(f"Creating index '{name}'")
            indexes.append(new_entry)

        # Always use array-of-tables format for consistency with uv
        aot = tomlkit.aot()
        for idx in indexes:
            if hasattr(idx, 'items'):  # Already a tomlkit table
                aot.append(idx)
            else:
                # Convert plain dict to table
                tbl = tomlkit.table()
                for k, v in idx.items():
                    tbl[k] = v
                aot.append(tbl)

        config['tool']['uv']['index'] = aot
        self.save(config)

    def add_source(self, package_name: str, source: dict) -> None:
        """Add a source mapping to [tool.uv.sources]."""
        config = self.load()
        self.ensure_section(config, 'tool', 'uv')

        if 'sources' not in config['tool']['uv']:
            config['tool']['uv']['sources'] = {}

        config['tool']['uv']['sources'][package_name] = source
        logger.info(f"Added source for '{package_name}': {source}")
        self.save(config)

    def add_url_sources(self, package_name: str, urls_with_markers: list[dict], group: str | None = None) -> None:
        """Add URL sources with markers to [tool.uv.sources]."""
        config = self.load()
        self.ensure_section(config, 'tool', 'uv')

        if 'sources' not in config['tool']['uv']:
            config['tool']['uv']['sources'] = {}

        # Clean up markers
        cleaned_sources = []
        for source in urls_with_markers:
            cleaned_source = {'url': source['url']}
            if source.get('marker'):
                cleaned_marker = source['marker'].replace('\\"', '"').replace("\\'", "'")
                cleaned_source['marker'] = cleaned_marker
            cleaned_sources.append(cleaned_source)

        # Format sources
        if len(cleaned_sources) > 1:
            config['tool']['uv']['sources'][package_name] = cleaned_sources
        else:
            config['tool']['uv']['sources'][package_name] = cleaned_sources[0]

        # Add to dependency group if specified
        if group:
            self._add_to_dependency_group(config, group, package_name, urls_with_markers)

        self.save(config)

    def get_constraints(self) -> list[str]:
        """Get UV constraint dependencies."""
        try:
            config = self.load()
            return config.get('tool', {}).get('uv', {}).get('constraint-dependencies', [])
        except Exception:
            return []

    def get_indexes(self) -> list[dict]:
        """Get UV indexes."""
        try:
            config = self.load()
            indexes = config.get('tool', {}).get('uv', {}).get('index', [])
            return indexes if isinstance(indexes, list) else [indexes] if indexes else []
        except Exception:
            return []

    def get_sources(self) -> dict:
        """Get UV source mappings."""
        try:
            config = self.load()
            return config.get('tool', {}).get('uv', {}).get('sources', {})
        except Exception:
            return {}

    def get_source_names(self) -> set[str]:
        """Get all UV source package names."""
        return set(self.get_sources().keys())

    def cleanup_orphaned_sources(self, removed_node_sources: list[str]) -> None:
        """Remove sources that are no longer referenced by any nodes."""
        if not removed_node_sources:
            return

        config = self.load()

        # Get all remaining nodes and their sources
        remaining_sources = set()
        if hasattr(self.manager, 'nodes'):
            for node_info in self.manager.nodes.get_existing().values():
                if node_info.dependency_sources:
                    remaining_sources.update(node_info.dependency_sources)

        # Remove orphaned sources (not protected, not used by other nodes)
        sources_removed = False
        for source_name in removed_node_sources:
            if (source_name not in remaining_sources and
                not self._is_protected_source(source_name)):
                self._remove_source(config, source_name)
                sources_removed = True

        if sources_removed:
            self.save(config)

    def _is_protected_source(self, source_name: str) -> bool:
        """Check if source should never be auto-removed."""
        return any(protected in source_name.lower() for protected in self.PROTECTED_SOURCES)

    def _remove_source(self, config: dict, source_name: str) -> None:
        """Remove all source entries for a given package."""
        if 'tool' not in config or 'uv' not in config['tool']:
            return

        sources = config['tool']['uv'].get('sources', {})
        if source_name in sources:
            del sources[source_name]
            logger.info(f"Removed orphaned source: {source_name}")

    def _extract_package_name(self, package_spec: str) -> str:
        """Extract package name from a version specification."""
        name, _ = parse_dependency_string(package_spec)
        return name.lower()

    def _add_to_dependency_group(self, config: dict, group: str, package: str, sources: list[dict]) -> None:
        """Internal helper to add a package to a dependency group with markers."""
        if 'dependency-groups' not in config:
            config['dependency-groups'] = {}

        if group not in config['dependency-groups']:
            config['dependency-groups'][group] = []

        group_deps = config['dependency-groups'][group]

        # Check if package already exists
        pkg_name = self._extract_package_name(package)
        for dep in group_deps:
            if self._extract_package_name(dep) == pkg_name:
                return  # Already exists

        # Add with unique markers
        unique_markers = set()
        for source in sources:
            if source.get('marker'):
                unique_markers.add(source['marker'])

        if unique_markers:
            for marker in unique_markers:
                entry = f"{package} ; {marker}"
                if entry not in group_deps:
                    group_deps.append(entry)
                    logger.info(f"Added '{entry}' to group '{group}'")
        else:
            group_deps.append(package)
            logger.info(f"Added '{package}' to group '{group}'")

    def set_exclude_dependencies(self, packages: list[str]) -> None:
        """Set exclude-dependencies list, replacing any existing values.

        This is the primary method for syncing exclusions from package_config.toml.
        If packages list is empty, removes the exclude-dependencies key entirely.

        Args:
            packages: List of package names to exclude (replaces existing)
        """
        config = self.load()
        self.ensure_section(config, 'tool', 'uv')

        if packages:
            config['tool']['uv']['exclude-dependencies'] = sorted(packages)
            self.save(config)
            logger.debug(f"Set package exclusions: {sorted(packages)}")
        else:
            # Empty list = remove the key entirely
            if 'exclude-dependencies' in config['tool']['uv']:
                del config['tool']['uv']['exclude-dependencies']
                self.save(config)
                logger.debug("Removed package exclusions (empty list)")
