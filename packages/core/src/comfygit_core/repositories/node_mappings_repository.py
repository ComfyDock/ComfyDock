"""Repository for node mappings data access - loads and provides query interface for global node mappings."""

from __future__ import annotations

import json
from functools import cached_property
from typing import TYPE_CHECKING

from ..logging.logging_config import get_logger
from ..models.node_mapping import (
    GlobalNodeMapping,
    GlobalNodeMappings,
    GlobalNodeMappingsStats,
    GlobalNodePackage,
    GlobalNodePackageVersion,
    PackageMapping,
)
from ..utils.git import normalize_github_url

if TYPE_CHECKING:
    from ..services.registry_data_manager import RegistryDataManager

logger = get_logger(__name__)


class NodeMappingsRepository:
    """Repository for accessing global node mappings data.

    Responsible for:
    - Loading mappings JSON file
    - Building indexes (GitHub URL -> package)
    - Providing simple query interface
    """

    def __init__(self, data_manager: RegistryDataManager):
        """Initialize repository with data manager.

        Args:
            data_manager: RegistryDataManager that handles freshness and caching

        Raises:
            CDRegistryDataError: If mappings file doesn't exist after freshness check
        """
        from ..models.exceptions import CDRegistryDataError

        self.data_manager = data_manager
        # Staleness check happens here - data_manager ensures file is fresh
        self.mappings_path = data_manager.get_mappings_path()

        if not self.mappings_path.exists():
            raise CDRegistryDataError(
                message="Registry node mappings not available. The mappings file was not found after attempting to fetch it.",
                cache_path=str(self.mappings_path.parent),
                can_retry=True
            )

    @cached_property
    def global_mappings(self) -> GlobalNodeMappings:
        """Get cached global mappings (loads on first access)."""
        return self._load_mappings()

    @cached_property
    def github_to_registry(self) -> dict[str, GlobalNodePackage]:
        """Get cached GitHub URL to package mapping."""
        return self._build_github_to_registry_map(self.global_mappings)

    def _load_mappings(self) -> GlobalNodeMappings:
        """Load global mappings from JSON file.

        Returns:
            GlobalNodeMappings with parsed data structures

        Raises:
            json.JSONDecodeError: If file contains invalid JSON
            OSError: If file cannot be read
        """
        try:
            with open(self.mappings_path, encoding='utf-8') as f:
                data = json.load(f)

            # Load stats
            stats_data = data.get("stats", {})
            stats = GlobalNodeMappingsStats(
                packages=stats_data.get("packages"),
                signatures=stats_data.get("signatures"),
                total_nodes=stats_data.get("total_nodes"),
                augmented=stats_data.get("augmented"),
                augmentation_date=stats_data.get("augmentation_date"),
                nodes_from_manager=stats_data.get("nodes_from_manager"),
                manager_packages=stats_data.get("manager_packages"),
            )

            # Convert mappings dict to GlobalNodeMapping objects
            mappings = {}
            for key, mapping_data in data.get("mappings", {}).items():
                package_mappings = []

                # mapping_data is an array of PackageMapping dicts
                for pkg_mapping in mapping_data:
                    package_mappings.append(PackageMapping(
                        package_id=pkg_mapping["package_id"],
                        versions=pkg_mapping.get("versions", []),
                        rank=pkg_mapping["rank"],
                        source=pkg_mapping.get("source")
                    ))

                mappings[key] = GlobalNodeMapping(
                    id=key,
                    packages=package_mappings
                )

            raw_aliases = data.get("package_aliases", {})
            package_aliases = {}
            if isinstance(raw_aliases, dict):
                for legacy_id, canonical_id in raw_aliases.items():
                    if not isinstance(legacy_id, str) or not isinstance(canonical_id, str):
                        continue
                    if legacy_id == canonical_id:
                        continue
                    package_aliases[legacy_id] = canonical_id

            # Convert packages dict to GlobalNodePackage objects
            packages = {}
            for pkg_id, pkg_data in data.get("packages", {}).items():
                # Loop over versions and create global node package version objects
                versions: dict[str, GlobalNodePackageVersion] = {}
                pkg_versions = pkg_data.get("versions", {})
                for version_id, version_data in pkg_versions.items():
                    version = GlobalNodePackageVersion(
                        version=version_id,
                        changelog=version_data.get("changelog"),
                        release_date=version_data.get("release_date"),
                        dependencies=version_data.get("dependencies"),
                        deprecated=version_data.get("deprecated"),
                        download_url=version_data.get("download_url"),
                        status=version_data.get("status"),
                        supported_accelerators=version_data.get("supported_accelerators"),
                        supported_comfyui_version=version_data.get("supported_comfyui_version"),
                        supported_os=version_data.get("supported_os"),
                    )
                    versions[version_id] = version

                packages[pkg_id] = GlobalNodePackage(
                    id=pkg_id,
                    display_name=pkg_data.get("display_name"),
                    author=pkg_data.get("author"),
                    description=pkg_data.get("description"),
                    repository=pkg_data.get("repository"),
                    downloads=pkg_data.get("downloads"),
                    github_stars=pkg_data.get("github_stars"),
                    rating=pkg_data.get("rating"),
                    license=pkg_data.get("license"),
                    category=pkg_data.get("category"),
                    icon=pkg_data.get("icon"),
                    tags=pkg_data.get("tags"),
                    status=pkg_data.get("status"),
                    created_at=pkg_data.get("created_at"),
                    versions=versions,
                    source=pkg_data.get("source"),
                )

            global_mappings = GlobalNodeMappings(
                version=data.get("version", "unknown"),
                generated_at=data.get("generated_at", ""),
                stats=stats,
                mappings=mappings,
                packages=packages,
                package_aliases=package_aliases,
            )

            if stats:
                logger.info(
                    f"Loaded global mappings: {stats.signatures} signatures "
                    f"from {stats.packages} packages"
                )

            return global_mappings

        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load global mappings: {e}")
            raise

    def _build_github_to_registry_map(self, global_mappings: GlobalNodeMappings) -> dict[str, GlobalNodePackage]:
        """Build reverse mapping from GitHub URLs to registry packages.

        Args:
            global_mappings: Loaded mappings data

        Returns:
            Dict mapping normalized GitHub URLs to packages
        """
        github_to_registry = {}

        for _, package in global_mappings.packages.items():
            if package.repository:
                normalized_url = normalize_github_url(package.repository)
                if normalized_url:
                    github_to_registry[normalized_url] = package

        logger.debug(f"Built GitHub to registry map with {len(github_to_registry)} entries")
        return github_to_registry

    # Query Methods

    def canonicalize_package_id(self, package_id: str | None) -> str | None:
        """Convert alias package IDs to canonical IDs from mappings metadata."""
        if not package_id:
            return package_id

        aliases = self.global_mappings.package_aliases
        current = package_id
        seen = set()
        while current in aliases:
            if current in seen:
                logger.warning("Detected cyclic package alias while canonicalizing '%s'", package_id)
                break
            seen.add(current)
            next_id = aliases[current]
            if not next_id:
                break
            current = next_id
        return current

    def get_package(self, package_id: str) -> GlobalNodePackage | None:
        """Get package by ID.

        Args:
            package_id: Package identifier

        Returns:
            GlobalNodePackage or None if not found
        """
        canonical_id = self.canonicalize_package_id(package_id)
        if not canonical_id:
            return None
        return self.global_mappings.packages.get(canonical_id)

    def get_mapping(self, node_key: str) -> GlobalNodeMapping | None:
        """Get mapping by node key (e.g., "NodeType::input_hash").

        Args:
            node_key: Node mapping key

        Returns:
            GlobalNodeMapping or None if not found
        """
        return self.global_mappings.mappings.get(node_key)

    def get_all_packages(self) -> dict[str, GlobalNodePackage]:
        """Get all packages.

        Returns:
            Dict of package_id -> GlobalNodePackage
        """
        return self.global_mappings.packages

    def resolve_github_url(self, github_url: str) -> GlobalNodePackage | None:
        """Resolve GitHub URL to registry package.

        Args:
            github_url: GitHub repository URL (any format)

        Returns:
            GlobalNodePackage if URL maps to registry package, None otherwise
        """
        normalized_url = normalize_github_url(github_url)
        return self.github_to_registry.get(normalized_url)

    def get_github_url_for_package(self, package_id: str) -> str | None:
        """Get GitHub URL for a package ID.

        Args:
            package_id: Package identifier

        Returns:
            GitHub URL or None if package not found or has no repository
        """
        package = self.get_package(package_id)
        return package.repository if package else None
