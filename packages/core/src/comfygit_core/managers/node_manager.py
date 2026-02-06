# managers/node_manager.py
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from ..analyzers.node_git_analyzer import get_node_git_info
from ..logging.logging_config import get_logger
from ..managers.pyproject_manager import PyprojectManager
from ..managers.uv_project_manager import UVProjectManager
from ..models.exceptions import (
    CDDependencyConflictError,
    CDEnvironmentError,
    CDNodeConflictError,
    CDNodeNotFoundError,
    DependencyConflictContext,
    NodeAction,
    NodeConflictContext,
)
from ..models.shared import NodeInfo, NodePackage, NodeRemovalResult, UpdateResult
from ..services.node_lookup_service import NodeLookupService
from ..strategies.confirmation import AutoConfirmStrategy, ConfirmationStrategy
from ..utils.conflict_parser import extract_conflicting_packages
from ..utils.dependency_parser import parse_dependency_string
from ..utils.filesystem import rmtree
from ..utils.git import git_clone, is_github_url, normalize_github_url
from ..validation.resolution_tester import ResolutionTester

if TYPE_CHECKING:
    from ..configs.package_config import PackageConfigManager
    from ..managers.pytorch_backend_manager import PyTorchBackendManager
    from ..repositories.node_mappings_repository import NodeMappingsRepository

logger = get_logger(__name__)


class NodeManager:
    """Manages all node operations for an environment."""

    def __init__(
        self,
        pyproject: PyprojectManager,
        uv: UVProjectManager,
        node_lookup: NodeLookupService,
        resolution_tester: ResolutionTester,
        custom_nodes_path: Path,
        node_repository: NodeMappingsRepository,
        pytorch_manager: PyTorchBackendManager | None = None,
        package_config: PackageConfigManager | None = None,
    ):
        self.pyproject = pyproject
        self.uv = uv
        self.node_lookup = node_lookup
        self.resolution_tester = resolution_tester
        self.custom_nodes_path = custom_nodes_path
        self.node_repository = node_repository
        self.pytorch_manager = pytorch_manager
        self.package_config = package_config

    def _resolve_sync_extras(
        self,
        extras: list[str] | None,
        all_extras: bool
    ) -> tuple[list[str] | None, bool]:
        resolver = getattr(self.pyproject, "resolve_sync_extras", None)
        if callable(resolver):
            resolved = resolver(extras, all_extras)
            if isinstance(resolved, tuple) and len(resolved) == 2:
                return resolved
        return extras, all_extras

    def _sync_uv(self, **kwargs) -> None:
        extras = kwargs.pop("extras", None)
        all_extras = kwargs.pop("all_extras", False)
        resolved_extras, resolved_all = self._resolve_sync_extras(extras, all_extras)
        self.uv.sync_project(extras=resolved_extras, all_extras=resolved_all, **kwargs)

    def _find_node_by_name(self, name: str) -> tuple[str, NodeInfo] | None:
        """Find a node by name across all identifiers (case-insensitive).

        Returns:
            Tuple of (identifier, node_info) if found, None otherwise
        """
        existing_nodes = self.pyproject.nodes.get_existing()
        name_lower = name.lower()
        for identifier, node_info in existing_nodes.items():
            if node_info.name.lower() == name_lower:
                return identifier, node_info
        return None

    def _install_node_from_info(self, node_info: NodeInfo, no_test: bool = False) -> NodeInfo:
        """Install a node given a pre-fetched NodeInfo object.

        This bypasses the lookup/cache layer and directly installs the node
        using the provided node info. Useful for update operations where we've
        already fetched fresh data from the API.

        Args:
            node_info: Pre-fetched node information from API
            no_test: Skip dependency resolution testing

        Returns:
            NodeInfo of the installed node

        Raises:
            CDEnvironmentError: If installation fails
            CDNodeConflictError: If dependency conflicts detected
        """
        # Download to cache
        cache_path = self.node_lookup.download_to_cache(node_info)
        if not cache_path:
            raise CDEnvironmentError(f"Failed to download node '{node_info.name}'")

        # Scan requirements from cached directory
        requirements = self.node_lookup.scan_requirements(cache_path, package_config=self.package_config)

        # Create node package
        node_package = NodePackage(node_info=node_info, requirements=requirements)

        # TEST DEPENDENCIES FIRST (before any filesystem or pyproject changes)
        if not no_test and node_package.requirements:
            logger.info(f"Testing dependency resolution for '{node_package.name}' before installation")
            test_result = self._test_requirements_in_isolation(node_package.requirements)
            if not test_result.success:
                # Pass first requirement as package_spec for conflict analysis
                pkg_spec = node_package.requirements[0] if node_package.requirements else None
                self._raise_dependency_conflict(node_package.name, test_result, package_spec=pkg_spec)

        # === BEGIN TRANSACTIONAL SECTION ===
        # Snapshot state before any modifications for rollback
        pyproject_snapshot = self.pyproject.snapshot()
        target_path = self.custom_nodes_path / node_info.name
        disabled_path = self.custom_nodes_path / f"{node_info.name}.disabled"

        try:
            # STEP 1: Filesystem changes
            # Note: .disabled is NOT deleted here — callers (update flows) clean it up on success
            shutil.copytree(cache_path, target_path, dirs_exist_ok=True)
            logger.info(f"Installed node '{node_info.name}' to {target_path}")

            # STEP 2: Pyproject changes
            self.add_node_package(node_package)

            # STEP 3: Environment sync (quiet - users see our high-level messages)
            self._sync_uv(quiet=True, all_groups=True, pytorch_manager=self.pytorch_manager)

        except Exception as e:
            # === ROLLBACK ===
            logger.warning(f"Installation failed for '{node_info.name}', rolling back...")

            # 1. Restore pyproject.toml
            try:
                self.pyproject.restore(pyproject_snapshot)
                logger.debug("Restored pyproject.toml to pre-installation state")
            except Exception as restore_err:
                logger.error(f"Failed to restore pyproject.toml: {restore_err}")

            # 2. Clean up filesystem
            if target_path.exists():
                try:
                    rmtree(target_path)
                    logger.debug(f"Removed {target_path}")
                except Exception as fs_err:
                    logger.error(f"Failed to clean up {target_path}: {fs_err}")

            # 3. Re-sync venv to match restored pyproject.toml
            try:
                self._sync_uv(quiet=True, all_groups=True, pytorch_manager=self.pytorch_manager)
            except Exception as sync_err:
                logger.error(f"Failed to re-sync environment after rollback: {sync_err}")
                logger.error("Environment may be inconsistent. Run 'cg env sync' to repair.")

            raise CDEnvironmentError(f"Failed to install node '{node_info.name}': {e}") from e

        # Success — clean up .disabled if present (left by update flows)
        if disabled_path.exists():
            try:
                rmtree(disabled_path)
                logger.debug(f"Cleaned up old disabled version of {node_info.name}")
            except Exception:
                pass  # Non-critical cleanup

        logger.info(f"Successfully added node: {node_info.name}")
        return node_info

    def add_node_package(self, node_package: NodePackage) -> None:
        """Add a complete node package with requirements and source tracking.

        This is the low-level method for adding pre-prepared node packages.
        """
        # Check for duplicates by name (regardless of identifier)
        existing = self._find_node_by_name(node_package.name)
        if existing:
            existing_id, existing_node = existing
            node_type = "development" if existing_node.version == 'dev' else "regular"

            context = NodeConflictContext(
                conflict_type='already_tracked',
                node_name=node_package.name,
                existing_identifier=existing_id,
                is_development=(existing_node.version == 'dev'),
                suggested_actions=[
                    NodeAction(
                        action_type='remove_node',
                        node_identifier=existing_id,
                        description=f"Remove existing {node_type} node"
                    )
                ]
            )

            raise CDNodeConflictError(
                f"Node '{node_package.name}' already exists as {node_type} node (identifier: '{existing_id}')",
                context=context
            )

        # Snapshot sources before processing
        existing_sources = self.pyproject.uv_config.get_source_names()

        # Generate collision-resistant group name for UV dependencies
        group_name = self.pyproject.nodes.generate_group_name(
            node_package.node_info, node_package.identifier
        )

        # Add requirements if any
        if node_package.requirements:
            self.uv.add_requirements_with_sources(
                node_package.requirements, group=group_name, no_sync=True, raw=True
            )

        # Detect new sources after processing
        current_sources = self.pyproject.uv_config.get_source_names()
        new_sources = current_sources - existing_sources

        # Update node with detected sources
        if new_sources:
            node_package.node_info.dependency_sources = sorted(new_sources)

        # Store node configuration
        self.pyproject.nodes.add(node_package.node_info, node_package.identifier)

    def add_node(
        self,
        identifier: str,
        is_development: bool = False,
        no_test: bool = False,
        force: bool = False,
        confirmation_strategy: ConfirmationStrategy | None = None,
        strict: bool = False,
        extras: list[str] | None = None,
        all_extras: bool = False,
    ) -> NodeInfo:
        """Add a custom node to the environment.

        Args:
            identifier: Registry ID or GitHub URL of the node (supports @version)
            is_development: If the node is a development node
            no_test: Skip testing the node
            force: Force replacement of existing nodes
            confirmation_strategy: Strategy for confirming replacements
            strict: If True, fail on dependency conflicts instead of auto-resolving
            extras: Optional list of extras to install during sync
            all_extras: Install all optional extras during sync

        Raises:
            CDNodeNotFoundError: If node not found
            CDNodeConflictError: If node has dependency conflicts
            CDEnvironmentError: If node with same name already exists
            ValueError: If trying to add a system node
        """
        logger.info(f"Adding node: {identifier}")

        # Handle development nodes
        if is_development:
            return self._add_development_node(identifier)

        # Check for existing installation by registry ID (if GitHub URL provided)
        registry_id = None
        github_url = None
        user_specified_version = '@' in identifier  # Track if user explicitly specified a version

        if is_github_url(identifier):
            github_url = identifier
            # Try to resolve GitHub URL to registry ID
            if resolved := self.node_repository.resolve_github_url(identifier):
                registry_id = resolved.id
                logger.info(f"Resolved GitHub URL to registry ID: {registry_id}")
            else:
                # Not in registry - fall through to direct git installation
                # This allows installation of any GitHub repo, not just registered ones
                logger.info(f"GitHub URL not in registry, will install as pure git node: {identifier}")
        else:
            # Parse base identifier (strip version if present)
            base_identifier = identifier.split('@')[0] if '@' in identifier else identifier
            registry_id = base_identifier

        # Get node info from lookup service (this parses @version)
        node_info = self.node_lookup.get_node(identifier)

        # Enhance with dual-source information if available
        if github_url and registry_id:
            node_info.registry_id = registry_id
            node_info.repository = github_url
            logger.info(f"Enhanced node info with dual sources: registry_id={registry_id}, github_url={github_url}")

        # Check for existing installation and handle version replacement
        is_replacement = False
        existing_entry = self._find_node_by_name(node_info.name)
        if existing_entry:
            existing_identifier, existing_node = existing_entry

            # If user didn't specify a version, error (don't auto-upgrade to latest)
            if not user_specified_version:
                raise CDNodeConflictError(
                    f"Node '{node_info.name}' is already installed (version {existing_node.version})",
                    context=NodeConflictContext(
                        conflict_type='already_tracked',
                        node_name=node_info.name,
                        existing_identifier=existing_identifier,
                        is_development=(existing_node.version == 'dev'),
                        suggested_actions=[
                            NodeAction(
                                action_type='update_node',
                                node_identifier=existing_identifier,
                                description="Update to latest version"
                            ),
                            NodeAction(
                                action_type='add_node_version',
                                node_identifier=f"{existing_identifier}@<version>",
                                description="Install specific version"
                            )
                        ]
                    )
                )

            # Check if same version
            if existing_node.version == node_info.version:
                raise CDNodeConflictError(
                    f"Node '{node_info.name}' version {node_info.version} is already installed",
                    context=NodeConflictContext(
                        conflict_type='already_tracked',
                        node_name=node_info.name,
                        existing_identifier=existing_identifier,
                        is_development=(existing_node.version == 'dev')
                    )
                )

            # Different version - handle replacement
            if existing_node.source == 'development':
                # Dev node replacement requires confirmation unless forced
                if not force:
                    if confirmation_strategy is None:
                        raise CDNodeConflictError(
                            f"Cannot replace development node '{node_info.name}' without confirmation. "
                            f"Use --force to replace or provide confirmation strategy.",
                            context=NodeConflictContext(
                                conflict_type='dev_node_replacement',
                                node_name=node_info.name,
                                existing_identifier=existing_identifier,
                                is_development=True
                            )
                        )

                    # Use strategy to confirm (with fallbacks for None versions)
                    current_ver = existing_node.version or 'unknown'
                    new_ver = node_info.version or 'unknown'
                    confirmed = confirmation_strategy.confirm_replace_dev_node(
                        node_info.name, current_ver, new_ver
                    )

                    if not confirmed:
                        raise CDNodeConflictError(
                            f"User declined replacement of development node '{node_info.name}'",
                            context=NodeConflictContext(
                                conflict_type='user_cancelled',
                                node_name=node_info.name,
                                existing_identifier=existing_identifier,
                                is_development=True
                            )
                        )

            # Mark as replacement — actual removal happens inside transactional section
            # so the snapshot captures pre-replacement state for proper rollback
            logger.info(f"Replacing {node_info.name} {existing_node.version} → {node_info.version}")
            is_replacement = True

        # Check for filesystem conflicts before proceeding
        # Skip during replacement — directory is expected to exist (it's the node we're replacing)
        if not force and not is_replacement:
            has_conflict, conflict_msg, conflict_context = self._check_filesystem_conflict(
                node_info.name,
                expected_repo_url=node_info.repository
            )
            if has_conflict:
                raise CDNodeConflictError(conflict_msg, context=conflict_context)

        # Download to cache (but don't install yet)
        cache_path = self.node_lookup.download_to_cache(node_info)
        if not cache_path:
            raise CDEnvironmentError(f"Failed to download node '{node_info.name}'")

        # Scan requirements from cached directory
        requirements = self.node_lookup.scan_requirements(cache_path, package_config=self.package_config)

        # Create node package
        node_package = NodePackage(node_info=node_info, requirements=requirements)

        # DEPENDENCY PREFLIGHT (before filesystem install)
        # Default: probe and discover needed constraints
        # Strict mode: old behavior (fail on conflicts)
        discovered_constraints: list[str] = []

        if not no_test and node_package.requirements:
            if strict:
                # Old behavior - fail on conflict
                logger.info(f"Testing dependency resolution for '{node_package.name}' (strict mode)")
                test_result = self._test_requirements_in_isolation(node_package.requirements)
                if not test_result.success:
                    pkg_spec = node_package.requirements[0] if node_package.requirements else None
                    self._raise_dependency_conflict(node_package.name, test_result, package_spec=pkg_spec)
            else:
                # New behavior - probe and discover needed constraints
                logger.info(f"Probing dependencies for '{node_package.name}'")
                from ..utils.dependency_probe import DependencyProbe

                probe = DependencyProbe(
                    cec_path=self.pyproject.path.parent,
                    workspace_path=self.resolution_tester.workspace_path,
                )
                probe_result = probe.run(node_package.requirements)

                # If one-by-one installs fail, we can't safely infer constraints
                if probe_result.install_failures:
                    self._raise_probe_install_failures(node_package.name, probe_result)

                # If the probe would change protected packages, bail out
                if probe_result.protected_changes:
                    self._raise_probe_protected_changes(node_package.name, probe_result)

                discovered_constraints = probe_result.suggested_constraints

                if discovered_constraints:
                    logger.info(
                        f"Probe discovered {len(discovered_constraints)} constraint(s): "
                        + ", ".join(discovered_constraints)
                    )

                    # Validate constraints don't conflict with existing environment
                    # This catches issues BEFORE modifying pyproject.toml
                    self._validate_constraints_against_environment(
                        node_package.name,
                        discovered_constraints,
                        node_package.requirements,
                    )

        # === BEGIN TRANSACTIONAL SECTION ===
        # Snapshot state before any modifications for rollback
        pyproject_snapshot = self.pyproject.snapshot()
        target_path = self.custom_nodes_path / node_info.name
        disabled_path = self.custom_nodes_path / f"{node_info.name}.disabled"

        try:
            # STEP 0a: Handle replacement — back up old node (inside transaction for proper rollback)
            if is_replacement:
                if target_path.exists():
                    if disabled_path.exists():
                        rmtree(disabled_path)
                    shutil.move(target_path, disabled_path)
                self.pyproject.nodes.remove(existing_identifier)
                self._sync_uv(
                    quiet=True,
                    all_groups=True,
                    pytorch_manager=self.pytorch_manager,
                    extras=extras,
                    all_extras=all_extras,
                )

            # STEP 0b: Apply auto-discovered constraints (transactional)
            for constraint in discovered_constraints:
                self.pyproject.uv_config.add_constraint(constraint)
                logger.info(f"Auto-applied constraint: {constraint}")

            # STEP 1: Filesystem changes
            # Note: .disabled is NOT deleted here — cleaned up on success below
            shutil.copytree(cache_path, target_path, dirs_exist_ok=True)
            logger.info(f"Installed node '{node_info.name}' to {target_path}")

            # STEP 2: Pyproject changes
            self.add_node_package(node_package)

            # STEP 3: Environment sync (quiet - users see our high-level messages)
            self._sync_uv(
                quiet=True,
                all_groups=True,
                pytorch_manager=self.pytorch_manager,
                extras=extras,
                all_extras=all_extras,
            )

        except Exception as e:
            # === ROLLBACK ===
            logger.warning(f"Installation failed for '{node_info.name}', rolling back...")

            # 1. Restore pyproject.toml
            try:
                self.pyproject.restore(pyproject_snapshot)
                logger.debug("Restored pyproject.toml to pre-installation state")
            except Exception as restore_err:
                logger.error(f"Failed to restore pyproject.toml: {restore_err}")

            # 2. Clean up filesystem
            if target_path.exists():
                try:
                    rmtree(target_path)
                    logger.debug(f"Removed {target_path}")
                except Exception as fs_err:
                    logger.warning(f"Could not remove {target_path} during rollback: {fs_err}")

            # 3. Restore from .disabled backup if replacement was in progress
            if disabled_path.exists() and not target_path.exists():
                try:
                    shutil.move(disabled_path, target_path)
                    logger.info(f"Restored old version of '{node_info.name}' from backup")
                except Exception as restore_err:
                    logger.error(f"Failed to restore old version: {restore_err}")

            # 4. Re-sync venv to match restored pyproject.toml
            try:
                self._sync_uv(
                    quiet=True,
                    all_groups=True,
                    pytorch_manager=self.pytorch_manager,
                    extras=extras,
                    all_extras=all_extras,
                )
            except Exception as sync_err:
                logger.error(f"Failed to re-sync environment after rollback: {sync_err}")
                logger.error("Environment may be inconsistent. Run 'cg env sync' to repair.")

            # 5. Re-raise with appropriate error type
            from ..models.exceptions import UVCommandError
            from ..utils.uv_error_handler import format_uv_error_for_user, log_uv_error

            if isinstance(e, UVCommandError):
                # Log full error details for debugging
                log_uv_error(logger, e, node_package.name)
                # Format concise message for user
                user_msg = format_uv_error_for_user(e)
                raise CDNodeConflictError(
                    f"Node '{node_package.name}' dependency sync failed: {user_msg}"
                ) from e
            elif "already exists" in str(e):
                raise CDEnvironmentError(str(e)) from e
            else:
                raise CDEnvironmentError(
                    f"Failed to add node '{node_package.name}': {e}"
                ) from e

        # === END TRANSACTIONAL SECTION ===

        # Success — clean up .disabled if present (from replacement or previous operation)
        if disabled_path.exists():
            try:
                rmtree(disabled_path)
                logger.debug(f"Cleaned up old disabled version of {node_info.name}")
            except Exception:
                pass  # Non-critical cleanup

        logger.info(f"Successfully added node '{node_package.name}'")
        return node_package.node_info

    def remove_node(self, identifier: str, untrack_only: bool = False):
        """Remove a custom node by identifier or name (case-insensitive).

        Handles filesystem changes imperatively based on node type:
        - Development nodes: Renamed to .disabled suffix (preserved)
        - Registry/Git nodes: Deleted from filesystem (cached globally)

        Args:
            identifier: Node identifier or name
            untrack_only: If True, only remove from pyproject.toml without touching filesystem

        Returns:
            NodeRemovalResult: Details about the removal

        Raises:
            CDNodeNotFoundError: If node not found
        """
        existing_nodes = self.pyproject.nodes.get_existing()
        identifier_lower = identifier.lower()

        # Try case-insensitive identifier lookup
        actual_identifier = None
        removed_node = None

        for key, node in existing_nodes.items():
            if key.lower() == identifier_lower:
                actual_identifier = key
                removed_node = node
                break

        if not actual_identifier:
            # Try name-based lookup as fallback
            found = self._find_node_by_name(identifier)
            if found:
                actual_identifier, removed_node = found
            else:
                # Check if untracked node exists on filesystem
                return self._remove_untracked_node(identifier)

        # At this point both must be set
        assert actual_identifier is not None
        assert removed_node is not None

        # Determine node type and filesystem action
        is_development = removed_node.source == 'development'
        node_path = self.custom_nodes_path / removed_node.name

        # Handle filesystem imperatively (unless untrack_only)
        filesystem_action = "none"
        if not untrack_only and node_path.exists():
            if is_development:
                # Developer manages their own code - just untrack, don't touch filesystem
                filesystem_action = "none"
                logger.info(f"Untracked development node: {removed_node.name} (filesystem unchanged)")
            else:
                # Delete registry/git node (cached globally, can re-download)
                rmtree(node_path)
                filesystem_action = "deleted"
                logger.info(f"Removed {removed_node.name} (cached, can reinstall)")

        # Remove from pyproject.toml
        removed = self.pyproject.nodes.remove(actual_identifier)
        if not removed:
            raise CDNodeNotFoundError(f"Node '{identifier}' not found in environment")

        # Clean up workflow references to this node
        self.pyproject.workflows.cleanup_node_references(actual_identifier, removed_node.name)

        # Clean up orphaned UV sources for registry/git nodes
        if not is_development:
            removed_sources = removed_node.dependency_sources or []
            self.pyproject.uv_config.cleanup_orphaned_sources(removed_sources)

        # Sync Python environment to remove orphaned packages (quiet - users see our high-level messages)
        self._sync_uv(quiet=True, all_groups=True, pytorch_manager=self.pytorch_manager)

        logger.info(f"Removed node '{actual_identifier}' from tracking")

        return NodeRemovalResult(
            identifier=actual_identifier,
            name=removed_node.name,
            source=removed_node.source,
            filesystem_action=filesystem_action
        )

    def _remove_untracked_node(self, node_name: str) -> NodeRemovalResult:
        """Remove an untracked node from filesystem only.

        Called when remove_node() can't find a tracked node but filesystem has it.
        Handles both regular directories and .disabled directories.

        Args:
            node_name: Name of the node directory

        Returns:
            NodeRemovalResult with details

        Raises:
            CDNodeNotFoundError: If node not found on filesystem either
        """
        node_path = self.custom_nodes_path / node_name
        disabled_path = self.custom_nodes_path / f"{node_name}.disabled"

        removed = False
        filesystem_action = "none"

        if node_path.exists() and node_path.is_dir():
            rmtree(node_path)
            removed = True
            filesystem_action = "deleted"
            logger.info(f"Removed untracked node directory: {node_name}")

        if disabled_path.exists() and disabled_path.is_dir():
            rmtree(disabled_path)
            removed = True
            filesystem_action = "deleted"
            logger.info(f"Removed disabled node directory: {node_name}.disabled")

        if not removed:
            raise CDNodeNotFoundError(f"Node '{node_name}' not found in environment")

        # Clean up any orphaned workflow references
        self.pyproject.workflows.cleanup_node_references(node_name)

        return NodeRemovalResult(
            identifier=node_name,
            name=node_name,
            source="untracked",
            filesystem_action=filesystem_action
        )

    def sync_nodes_to_filesystem(self, remove_extra: bool = False, callbacks=None):
        """Sync custom nodes directory to match expected state from pyproject.toml.

        Args:
            remove_extra: If True, aggressively remove ALL extra nodes (except ComfyUI builtins).
                         If False, only warn about extra nodes.
            callbacks: Optional NodeInstallCallbacks for progress feedback.

        Strategy:
        - Install missing registry/git nodes
        - Remove extra nodes (if remove_extra=True) or warn (if False)

        Note: When remove_extra=True, ALL untracked nodes are deleted regardless of whether
        they appear to be dev nodes. User confirmation is required before calling with this flag.
        """
        import shutil

        logger.info("Syncing custom nodes to filesystem...")

        # Ensure directory exists
        self.custom_nodes_path.mkdir(exist_ok=True)

        # Get expected nodes from pyproject.toml
        expected_nodes = self.pyproject.nodes.get_existing()

        # Get existing active nodes (not .disabled)
        existing_nodes = {
            d.name: d for d in self.custom_nodes_path.iterdir()
            if d.is_dir() and not d.name.endswith('.disabled')
        }

        expected_names = {info.name for info in expected_nodes.values()}
        untracked = set(existing_nodes.keys()) - expected_names

        if remove_extra:
            # ComfyUI's built-in files that should not be removed
            COMFYUI_BUILTINS = {'example_node.py.example', 'websocket_image_save.py', '__pycache__'}

            # Remove ALL untracked nodes (user confirmed deletion in repair preview)
            for node_name in untracked:
                # Skip ComfyUI built-ins
                if node_name in COMFYUI_BUILTINS:
                    continue

                node_path = self.custom_nodes_path / node_name
                rmtree(node_path)
                logger.info(f"Removed extra node: {node_name}")
        else:
            # Warn about extra nodes (don't auto-delete during manual sync)
            for node_name in untracked:
                logger.warning(f"Untracked node found: {node_name}")
                logger.warning(f"  Run 'cg node add {node_name} --dev' to track it")

        # Install missing registry/git nodes (skip if .disabled version exists)
        nodes_to_install = [
            node_info for node_info in expected_nodes.values()
            if node_info.source != 'development'
            and not (self.custom_nodes_path / node_info.name).exists()
            and not (self.custom_nodes_path / f"{node_info.name}.disabled").exists()
        ]

        if callbacks and callbacks.on_batch_start and nodes_to_install:
            callbacks.on_batch_start(len(nodes_to_install))

        success_count = 0
        for idx, node_info in enumerate(nodes_to_install):
            node_path = self.custom_nodes_path / node_info.name

            if callbacks and callbacks.on_node_start:
                callbacks.on_node_start(node_info.name, idx + 1, len(nodes_to_install))

            logger.info(f"Installing missing node: {node_info.name}")
            try:
                # Download to cache
                cache_path = self.node_lookup.download_to_cache(node_info)
                if cache_path:
                    shutil.copytree(cache_path, node_path, dirs_exist_ok=True)
                    logger.info(f"Successfully installed node: {node_info.name}")
                    success_count += 1
                    if callbacks and callbacks.on_node_complete:
                        callbacks.on_node_complete(node_info.name, True, None)
                else:
                    logger.warning(f"Could not download node '{node_info.name}'")
                    if callbacks and callbacks.on_node_complete:
                        callbacks.on_node_complete(node_info.name, False, "Download failed")
            except Exception as e:
                logger.warning(f"Could not download node '{node_info.name}': {e}")
                if callbacks and callbacks.on_node_complete:
                    callbacks.on_node_complete(node_info.name, False, str(e))

        if callbacks and callbacks.on_batch_complete and nodes_to_install:
            callbacks.on_batch_complete(success_count, len(nodes_to_install))

        # Handle missing dev nodes with repository (clone from git)
        self._sync_dev_nodes_from_git(expected_nodes, existing_nodes, callbacks)

        logger.info("Finished syncing custom nodes")

    def _sync_dev_nodes_from_git(self, expected_nodes: dict, existing_nodes: dict, callbacks=None):
        """Clone missing dev nodes that have repository URLs.

        Dev nodes with repository are cloned if missing locally.
        Dev nodes without repository trigger a warning callback.
        Dev nodes that already exist locally are skipped (local state is authoritative).

        Args:
            expected_nodes: Dict of identifier -> NodeInfo from pyproject.toml
            existing_nodes: Dict of node_name -> Path for nodes on filesystem
            callbacks: Optional callbacks for progress feedback
        """
        for _identifier, node_info in expected_nodes.items():
            if node_info.source != 'development':
                continue

            node_path = self.custom_nodes_path / node_info.name

            # Skip if already exists locally (local state is authoritative)
            if node_path.exists():
                logger.debug(f"Dev node '{node_info.name}' exists locally, skipping")
                continue

            # No repository - can't clone, warn via callback
            if not node_info.repository:
                logger.warning(f"Dev node '{node_info.name}' missing and has no repository")
                if callbacks and hasattr(callbacks, 'on_dev_node_missing_repository'):
                    callbacks.on_dev_node_missing_repository(node_info.name)
                continue

            # Clone from repository
            success = self._install_dev_node_from_git(node_info)
            if success and callbacks and hasattr(callbacks, 'on_dev_node_cloned'):
                callbacks.on_dev_node_cloned(node_info.name, node_info.repository)

    def _install_dev_node_from_git(self, node_info: NodeInfo) -> bool:
        """Clone dev node from git reference.

        Args:
            node_info: NodeInfo with repository and optional branch/pinned_commit

        Returns:
            True if successfully cloned, False otherwise
        """
        node_path = self.custom_nodes_path / node_info.name

        # Determine ref: branch takes priority over pinned_commit
        ref = node_info.branch or node_info.pinned_commit

        logger.info(f"Cloning dev node '{node_info.name}' from {node_info.repository}")
        if ref:
            logger.info(f"  Using ref: {ref}")

        try:
            # Full clone (depth=0) for dev nodes since developers will push changes
            git_clone(
                url=node_info.repository,
                target_path=node_path,
                depth=0,
                ref=ref
            )
            logger.info(f"Successfully cloned dev node: {node_info.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to clone dev node '{node_info.name}': {e}")
            return False

    def reconcile_nodes_for_rollback(self, old_nodes: dict[str, NodeInfo], new_nodes: dict[str, NodeInfo]):
        """Reconcile filesystem nodes after rollback with full context.

        Dev nodes are SKIPPED entirely - ComfyGit never touches their filesystem state.
        This ensures developer's local work is preserved during any git operation.

        Args:
            old_nodes: Nodes that were in pyproject before rollback
            new_nodes: Nodes that are in pyproject after rollback
        """
        import shutil

        # Nodes that were removed (in old, not in new)
        removed_node_names = set(old_nodes.keys()) - set(new_nodes.keys())

        for identifier in removed_node_names:
            old_node_info = old_nodes[identifier]

            # SKIP dev nodes entirely - never touch their filesystem state
            if old_node_info.source == 'development':
                logger.debug(f"Skipping dev node '{old_node_info.name}' during reconciliation")
                continue

            node_path = self.custom_nodes_path / old_node_info.name

            if not node_path.exists():
                continue  # Already gone

            # Registry/git node - delete it (cached globally, can reinstall)
            rmtree(node_path)
            logger.info(f"Removed '{old_node_info.name}' (rollback, cached)")

        # Nodes that were added (in new, not in old)
        added_node_identifiers = set(new_nodes.keys()) - set(old_nodes.keys())

        for identifier in added_node_identifiers:
            new_node_info = new_nodes[identifier]
            node_path = self.custom_nodes_path / new_node_info.name

            if node_path.exists():
                continue  # Already present

            # Install the node (skip dev nodes - user manages those)
            if new_node_info.source != 'development':
                logger.info(f"Installing '{new_node_info.name}' (rollback)")
                try:
                    cache_path = self.node_lookup.download_to_cache(new_node_info)
                    if cache_path:
                        shutil.copytree(cache_path, node_path, dirs_exist_ok=True)
                        logger.info(f"Successfully installed '{new_node_info.name}'")
                    else:
                        logger.warning(f"Could not download '{new_node_info.name}'")
                except Exception as e:
                    logger.warning(f"Failed to install '{new_node_info.name}': {e}")


    def _get_existing_node_by_registry_id(self, registry_id: str) -> dict:
        """Get existing node configuration by registry ID."""
        existing_nodes = self.pyproject.nodes.get_existing()
        for node_info in existing_nodes.values():
            if hasattr(node_info, 'registry_id') and node_info.registry_id == registry_id:
                return {
                    'name': node_info.name,
                    'registry_id': node_info.registry_id,
                    'version': node_info.version,
                    'repository': node_info.repository,
                    'source': node_info.source
                }
        return {}

    def _check_filesystem_conflict(
        self,
        node_name: str,
        expected_repo_url: str | None = None
    ) -> tuple[bool, str, NodeConflictContext | None]:
        """Check if node directory exists and might conflict.

        Args:
            node_name: Name of the node directory
            expected_repo_url: Expected repository URL (for comparison)

        Returns:
            (has_conflict, conflict_message, context)
        """
        node_path = self.custom_nodes_path / node_name

        if not node_path.exists():
            return False, "", None

        # Check if it's a git repo
        git_dir = node_path / '.git'
        if not git_dir.exists():
            context = NodeConflictContext(
                conflict_type='directory_exists_non_git',
                node_name=node_name,
                filesystem_path=str(node_path),
                suggested_actions=[
                    NodeAction(
                        action_type='add_node_dev',
                        node_name=node_name,
                        description="Track existing directory as development node"
                    ),
                    NodeAction(
                        action_type='add_node_force',
                        node_identifier='<identifier>',
                        description="Force replace existing directory"
                    )
                ]
            )
            msg = f"Directory '{node_name}' already exists in custom_nodes/"
            return True, msg, context

        # Get remote URL
        from ..utils.git import git_remote_get_url
        local_remote = git_remote_get_url(node_path)

        if not local_remote:
            context = NodeConflictContext(
                conflict_type='directory_exists_no_remote',
                node_name=node_name,
                filesystem_path=str(node_path),
                suggested_actions=[
                    NodeAction(
                        action_type='add_node_dev',
                        node_name=node_name,
                        description="Track local git repository as development node"
                    ),
                    NodeAction(
                        action_type='add_node_force',
                        node_identifier='<identifier>',
                        description="Replace with registry version"
                    )
                ]
            )
            msg = f"Git repository '{node_name}' exists locally (no remote)"
            return True, msg, context

        # Compare URLs if we have expected URL
        if expected_repo_url:
            if self._same_repository(local_remote, expected_repo_url):
                context = NodeConflictContext(
                    conflict_type='same_repo_exists',
                    node_name=node_name,
                    local_remote_url=local_remote,
                    expected_remote_url=expected_repo_url,
                    suggested_actions=[
                        NodeAction(
                            action_type='add_node_dev',
                            node_name=node_name,
                            description="Track existing git clone as development node"
                        ),
                        NodeAction(
                            action_type='add_node_force',
                            node_identifier='<identifier>',
                            description="Re-download from registry (replaces local)"
                        )
                    ]
                )
                msg = f"Git clone of '{node_name}' already exists"
                return True, msg, context
            else:
                context = NodeConflictContext(
                    conflict_type='different_repo_exists',
                    node_name=node_name,
                    local_remote_url=local_remote,
                    expected_remote_url=expected_repo_url,
                    suggested_actions=[
                        NodeAction(
                            action_type='rename_directory',
                            directory_name=node_name,
                            new_name=f"{node_name}-fork",
                            description="Rename your fork to avoid conflict"
                        ),
                        NodeAction(
                            action_type='add_node_force',
                            node_identifier='<identifier>',
                            description="Replace with registry version (deletes yours)"
                        )
                    ]
                )
                msg = f"Repository conflict for '{node_name}'"
                return True, msg, context

        # Have git repo but no expected URL to compare
        context = NodeConflictContext(
            conflict_type='directory_exists_no_remote',
            node_name=node_name,
            local_remote_url=local_remote,
            suggested_actions=[
                NodeAction(
                    action_type='add_node_dev',
                    node_name=node_name,
                    description="Track as development node"
                ),
                NodeAction(
                    action_type='add_node_force',
                    node_identifier='<identifier>',
                    description="Force replace"
                )
            ]
        )
        msg = f"Git repository '{node_name}' already exists"
        return True, msg, context

    @staticmethod
    def _same_repository(url1: str, url2: str) -> bool:
        """Check if two git URLs refer to the same repository.

        Normalizes various URL formats for comparison.
        """
        normalized1 = normalize_github_url(url1).lower()
        normalized2 = normalize_github_url(url2).lower()

        return normalized1 == normalized2

    def _add_development_node(self, identifier: str) -> NodeInfo:
        """Add a development node - downloads if needed, then tracks."""
        # Try to find existing directory (case-insensitive)
        node_path = None
        node_name: str | None = None

        # Check if identifier is a simple name (not URL)
        if not is_github_url(identifier):
            # Look for existing directory
            for item in self.custom_nodes_path.iterdir():
                if item.is_dir() and item.name.lower() == identifier.lower():
                    node_path = item
                    node_name = item.name
                    logger.info(f"Found existing node directory: {node_name}")
                    break

        # If not found locally, download it
        if not node_path:
            logger.info(f"Node not found locally, downloading: {identifier}")

            # Get node info from lookup service
            try:
                node_info = self.node_lookup.get_node(identifier)
            except CDNodeNotFoundError:
                # Not in registry either - provide helpful error
                if is_github_url(identifier):
                    raise CDNodeNotFoundError(
                        f"Cannot download from GitHub URL: {identifier}\n"
                        f"Ensure the URL is accessible and correctly formatted"
                    ) from None
                else:
                    raise CDNodeNotFoundError(
                        f"Node '{identifier}' not found in registry or filesystem.\n"
                        f"Provide a GitHub URL or ensure the directory exists in custom_nodes/"
                    ) from None

            node_name = node_info.name
            node_path = self.custom_nodes_path / node_name

            # Download to cache and copy to filesystem
            logger.info(f"Downloading node '{node_name}' to {node_path}")
            cache_path = self.node_lookup.download_to_cache(node_info)
            if not cache_path:
                raise CDEnvironmentError(f"Failed to download node '{node_name}'")
            shutil.copytree(cache_path, node_path, dirs_exist_ok=True)

        # At this point node_name and node_path must be set
        assert node_name is not None, "node_name should be set by now"
        assert node_path is not None, "node_path should be set by now"

        # Check for duplicate tracking
        existing = self._find_node_by_name(node_name)
        if existing:
            existing_id, existing_node = existing
            if existing_node.version == 'dev':
                logger.info(f"Development node '{node_name}' already tracked")
                return existing_node
            else:
                context = NodeConflictContext(
                    conflict_type='already_tracked',
                    node_name=node_name,
                    existing_identifier=existing_id,
                    is_development=False,
                    suggested_actions=[
                        NodeAction(
                            action_type='remove_node',
                            node_identifier=existing_id,
                            description="Remove existing regular node first"
                        )
                    ]
                )
                raise CDNodeConflictError(
                    f"Node '{node_name}' already tracked as regular node (identifier: '{existing_id}')",
                    context=context
                )

        # Scan for requirements
        requirements = self.node_lookup.scan_requirements(node_path, package_config=self.package_config)

        # Create as development node
        node_info = NodeInfo(name=node_name, version='dev', source='development')

        # Capture git info if available
        git_info = get_node_git_info(node_path)
        if git_info and git_info.remote_url:
            node_info.repository = git_info.remote_url
            if git_info.branch:
                node_info.branch = git_info.branch
            if git_info.commit:
                node_info.pinned_commit = git_info.commit
            logger.info(f"Captured git info for dev node: {git_info.remote_url}")

        node_package = NodePackage(node_info=node_info, requirements=requirements)

        # Add to pyproject
        self.add_node_package(node_package)

        logger.info(f"Successfully added development node: {node_name}")
        return node_info

    def update_node(
        self,
        identifier: str,
        confirmation_strategy: ConfirmationStrategy | None = None,
        no_test: bool = False
    ) -> UpdateResult:
        """Update a node based on its source type.

        Args:
            identifier: Node identifier or name
            confirmation_strategy: Strategy for confirming updates (None = auto-confirm)
            no_test: Skip resolution testing (dev nodes only)

        Returns:
            UpdateResult with details of what changed

        Raises:
            CDNodeNotFoundError: If node not found
            CDEnvironmentError: If node cannot be updated
        """
        # Default to auto-confirm if no strategy provided
        if confirmation_strategy is None:
            confirmation_strategy = AutoConfirmStrategy()

        # Get current node info
        nodes = self.pyproject.nodes.get_existing()
        node_info = None
        actual_identifier = None

        # Try direct identifier lookup first
        if identifier in nodes:
            node_info = nodes[identifier]
            actual_identifier = identifier
        else:
            # Try name-based lookup
            found = self._find_node_by_name(identifier)
            if found:
                actual_identifier, node_info = found

        if not node_info or not actual_identifier:
            raise CDNodeNotFoundError(f"Node '{identifier}' not found")

        # Dispatch based on source type
        if node_info.source == 'development':
            return self._update_development_node(actual_identifier, node_info, no_test)
        elif node_info.source == 'registry':
            return self._update_registry_node(actual_identifier, node_info, confirmation_strategy, no_test)
        elif node_info.source == 'git':
            return self._update_git_node(actual_identifier, node_info, confirmation_strategy, no_test)
        else:
            raise CDEnvironmentError(f"Unknown node source: {node_info.source}")

    def _update_development_node(
        self,
        identifier: str,
        node_info: NodeInfo,
        no_test: bool
    ) -> UpdateResult:
        """Update dev node by re-scanning requirements and git info.

        This snapshots the current state of the dev node (requirements + git info)
        so it can be committed and shared with collaborators.

        Args:
            identifier: Node identifier in pyproject
            node_info: Node info object
            no_test: Skip dependency resolution testing
        """
        result = UpdateResult(node_name=node_info.name, source='development')

        node_path = self.custom_nodes_path / node_info.name
        if not node_path.exists():
            raise CDNodeNotFoundError(f"Dev node directory not found: {node_path}")

        changes = []

        # Update version from node's pyproject.toml
        try:
            import tomllib
            node_pyproject = node_path / "pyproject.toml"
            if node_pyproject.exists():
                with open(node_pyproject, "rb") as f:
                    data = tomllib.load(f)
                    disk_version = data.get("project", {}).get("version")
                    if disk_version and disk_version != node_info.version:
                        node_info.version = disk_version
                        changes.append("version")
        except Exception:
            pass

        # Update git info (repo, branch, commit)
        git_info = get_node_git_info(node_path)
        if git_info and git_info.remote_url:
            if node_info.repository != git_info.remote_url:
                node_info.repository = git_info.remote_url
                changes.append("repository")
            if git_info.branch and node_info.branch != git_info.branch:
                node_info.branch = git_info.branch
                changes.append("branch")
            if git_info.commit and node_info.pinned_commit != git_info.commit:
                node_info.pinned_commit = git_info.commit
                changes.append("commit")

        # Scan current requirements
        current_reqs = self.node_lookup.scan_requirements(node_path, package_config=self.package_config)

        # Get stored requirements from dependency group
        group_name = self.pyproject.nodes.generate_group_name(node_info, identifier)
        stored_groups = self.pyproject.dependencies.get_groups()
        stored_reqs = stored_groups.get(group_name, [])

        # Compare full requirement strings (including version constraints)
        current_set = set(current_reqs)
        stored_set = set(stored_reqs)
        added = current_set - stored_set
        removed = stored_set - current_set
        reqs_changed = bool(added or removed)

        if reqs_changed:
            changes.append("requirements")
            # Update requirements - remove old group first to replace (not append)
            try:
                self.pyproject.dependencies.remove_group(group_name)
            except ValueError:
                pass  # Group didn't exist

            existing_sources = self.pyproject.uv_config.get_source_names()

            if current_reqs:
                self.uv.add_requirements_with_sources(
                    current_reqs, group=group_name, no_sync=True
                )

            # Detect new sources
            new_sources = self.pyproject.uv_config.get_source_names() - existing_sources
            if new_sources:
                node_info.dependency_sources = sorted(new_sources)

        if not changes:
            result.message = "No changes detected"
            return result

        # Save updated node info to pyproject
        self.pyproject.nodes.add(node_info, identifier)

        # Test resolution if requested
        if not no_test and reqs_changed:
            resolution_result = self.resolution_tester.test_resolution(self.pyproject.path)
            if not resolution_result.success:
                # Pass first added requirement as package_spec for conflict analysis
                pkg_spec = next(iter(added), None) if added else None
                self._raise_dependency_conflict(node_info.name, resolution_result, package_spec=pkg_spec)

        result.requirements_added = list(added)
        result.requirements_removed = list(removed)
        result.changed = True
        result.message = f"Updated: {', '.join(changes)}"

        # Sync Python environment to apply requirement changes
        if reqs_changed:
            self._sync_uv(quiet=True, all_groups=True, pytorch_manager=self.pytorch_manager)

        logger.info(f"Updated dev node '{node_info.name}': {result.message}")
        return result

    def _update_registry_node(
        self,
        identifier: str,
        node_info: NodeInfo,
        confirmation_strategy: ConfirmationStrategy,
        no_test: bool
    ) -> UpdateResult:
        """Update registry node to latest version with atomic rollback on failure."""
        result = UpdateResult(node_name=node_info.name, source='registry')

        if not node_info.registry_id:
            raise CDEnvironmentError(f"Node '{node_info.name}' has no registry_id")

        # Query registry for latest version
        try:
            registry_node = self.node_lookup.registry_client.get_node(node_info.registry_id)
        except Exception as e:
            result.message = f"Failed to check for updates: {e}"
            return result

        if not registry_node or not registry_node.latest_version:
            result.message = "No updates available (registry unavailable)"
            return result

        latest_version = registry_node.latest_version.version
        current_version = node_info.version or "unknown"

        if latest_version == current_version:
            result.message = f"Already at latest version ({current_version})"
            return result

        # Confirm update using strategy
        if not confirmation_strategy.confirm_update(node_info.name, current_version, latest_version):
            result.message = "Update cancelled by user"
            return result

        # === ATOMIC UPDATE WITH ROLLBACK ===
        # Preserve old node by disabling it instead of removing
        node_path = self.custom_nodes_path / node_info.name
        disabled_path = self.custom_nodes_path / f"{node_info.name}.disabled"
        pyproject_snapshot = self.pyproject.snapshot()

        try:
            # STEP 1: Disable old node (rename to .disabled)
            if node_path.exists():
                if disabled_path.exists():
                    # Clean up any existing .disabled from previous failed update
                    rmtree(disabled_path)
                shutil.move(node_path, disabled_path)
                logger.debug(f"Disabled old version of '{node_info.name}'")

            # STEP 2: Remove old node from tracking
            self.pyproject.nodes.remove(identifier)
            self._sync_uv(quiet=True, all_groups=True, pytorch_manager=self.pytorch_manager)

            # STEP 3: Get complete version data with downloadUrl from install endpoint
            complete_version = self.node_lookup.registry_client.install_node(
                node_info.registry_id,
                latest_version
            )

            if complete_version:
                # Replace incomplete version data with complete version
                registry_node.latest_version = complete_version

            # Create fresh node info from API response with complete data
            fresh_node_info = NodeInfo.from_registry_node(registry_node)

            # STEP 4: Install the new version
            self._install_node_from_info(fresh_node_info, no_test=no_test)

            # STEP 5: Success - delete old disabled version
            if disabled_path.exists():
                rmtree(disabled_path)
                logger.debug(f"Deleted old version of '{node_info.name}'")

        except Exception as e:
            # === ROLLBACK ===
            logger.warning(f"Update failed for '{node_info.name}', rolling back...")

            # 1. Restore pyproject.toml
            try:
                self.pyproject.restore(pyproject_snapshot)
                logger.debug("Restored pyproject.toml to pre-update state")
            except Exception as restore_err:
                logger.error(f"Failed to restore pyproject.toml: {restore_err}")

            # 2. Remove failed new installation
            if node_path.exists():
                try:
                    rmtree(node_path)
                    logger.debug(f"Removed failed installation of '{node_info.name}'")
                except Exception as cleanup_err:
                    logger.error(f"Failed to clean up new installation: {cleanup_err}")

            # 3. Restore old version from .disabled
            if disabled_path.exists():
                try:
                    shutil.move(disabled_path, node_path)
                    logger.info(f"Restored old version of '{node_info.name}'")
                except Exception as restore_err:
                    logger.error(f"Failed to restore old version: {restore_err}")

            # 4. Sync environment to restore old dependencies
            try:
                self._sync_uv(quiet=True, all_groups=True, pytorch_manager=self.pytorch_manager)
            except Exception:
                pass  # Best effort

            # Re-raise original error
            raise CDEnvironmentError(f"Failed to update node '{node_info.name}': {e}") from e

        result.old_version = current_version
        result.new_version = latest_version
        result.changed = True
        result.message = f"Updated from {current_version} → {latest_version}"

        logger.info(f"Updated registry node '{node_info.name}': {result.message}")
        return result

    def _update_git_node(
        self,
        identifier: str,
        node_info: NodeInfo,
        confirmation_strategy: ConfirmationStrategy,
        no_test: bool
    ) -> UpdateResult:
        """Update git node to latest commit with atomic rollback on failure."""
        result = UpdateResult(node_name=node_info.name, source='git')

        if not node_info.repository:
            raise CDEnvironmentError(f"Node '{node_info.name}' has no repository URL")

        # Query GitHub for latest commit
        try:
            repo_info = self.node_lookup.github_client.get_repository_info(node_info.repository)
        except Exception as e:
            result.message = f"Failed to check for updates: {e}"
            return result

        if not repo_info:
            result.message = "Failed to get repository information"
            return result

        latest_commit = repo_info.latest_commit
        current_commit = node_info.version or "unknown"

        # Format for display
        current_display = current_commit[:8] if current_commit != "unknown" else "unknown"
        latest_display = latest_commit[:8] if latest_commit else "unknown"

        if latest_commit == current_commit:
            result.message = f"Already at latest commit ({current_display})"
            return result

        # Confirm update using strategy (pass formatted versions for display)
        if not confirmation_strategy.confirm_update(node_info.name, current_display, latest_display):
            result.message = "Update cancelled by user"
            return result

        # === ATOMIC UPDATE WITH ROLLBACK ===
        node_path = self.custom_nodes_path / node_info.name
        disabled_path = self.custom_nodes_path / f"{node_info.name}.disabled"
        pyproject_snapshot = self.pyproject.snapshot()

        try:
            # STEP 1: Disable old node (rename to .disabled)
            if node_path.exists():
                if disabled_path.exists():
                    rmtree(disabled_path)
                shutil.move(node_path, disabled_path)
                logger.debug(f"Disabled old version of '{node_info.name}'")

            # STEP 2: Remove old node from tracking
            self.pyproject.nodes.remove(identifier)
            self._sync_uv(quiet=True, all_groups=True, pytorch_manager=self.pytorch_manager)

            # STEP 3: Create fresh node info from GitHub API response
            fresh_node_info = NodeInfo(
                name=repo_info.name,
                repository=repo_info.clone_url,
                source="git",
                version=repo_info.latest_commit
            )

            # STEP 4: Install the new version
            self._install_node_from_info(fresh_node_info, no_test=no_test)

            # STEP 5: Success - delete old disabled version
            if disabled_path.exists():
                rmtree(disabled_path)
                logger.debug(f"Deleted old version of '{node_info.name}'")

        except Exception as e:
            # === ROLLBACK ===
            logger.warning(f"Update failed for '{node_info.name}', rolling back...")

            # 1. Restore pyproject.toml
            try:
                self.pyproject.restore(pyproject_snapshot)
                logger.debug("Restored pyproject.toml to pre-update state")
            except Exception as restore_err:
                logger.error(f"Failed to restore pyproject.toml: {restore_err}")

            # 2. Remove failed new installation
            if node_path.exists():
                try:
                    rmtree(node_path)
                    logger.debug(f"Removed failed installation of '{node_info.name}'")
                except Exception as cleanup_err:
                    logger.error(f"Failed to clean up new installation: {cleanup_err}")

            # 3. Restore old version from .disabled
            if disabled_path.exists():
                try:
                    shutil.move(disabled_path, node_path)
                    logger.info(f"Restored old version of '{node_info.name}'")
                except Exception as restore_err:
                    logger.error(f"Failed to restore old version: {restore_err}")

            # 4. Sync environment to restore old dependencies
            try:
                self._sync_uv(quiet=True, all_groups=True, pytorch_manager=self.pytorch_manager)
            except Exception:
                pass  # Best effort

            # Re-raise original error
            raise CDEnvironmentError(f"Failed to update node '{node_info.name}': {e}") from e

        result.old_version = current_display
        result.new_version = latest_display
        result.changed = True
        result.message = f"Updated to latest commit ({latest_display})"

        logger.info(f"Updated git node '{node_info.name}': {result.message}")
        return result

    def check_development_node_drift(self) -> dict[str, tuple[set[str], set[str]]]:
        """Check if dev nodes have requirements drift.

        Returns:
            Dict mapping node_name -> (added_deps, removed_deps)
        """
        drift = {}
        nodes = self.pyproject.nodes.get_existing()

        for identifier, node_info in nodes.items():
            if node_info.source != 'development':
                continue

            node_path = self.custom_nodes_path / node_info.name
            if not node_path.exists():
                continue

            # Scan current requirements
            current_reqs = self.node_lookup.scan_requirements(node_path, package_config=self.package_config)

            # Get stored requirements from dependency group
            group_name = self.pyproject.nodes.generate_group_name(node_info, identifier)
            stored_groups = self.pyproject.dependencies.get_groups()
            stored_reqs = stored_groups.get(group_name, [])

            # Compare package names
            current_names = {parse_dependency_string(r)[0] for r in current_reqs}
            stored_names = {parse_dependency_string(r)[0] for r in stored_reqs}

            added = current_names - stored_names
            removed = stored_names - current_names

            if added or removed:
                drift[node_info.name] = (added, removed)

        return drift

    def _test_requirements_in_isolation(self, requirements: list[str]):
        """Test requirements in isolation without modifying pyproject.toml.

        Uses the resolution tester to check if requirements are compatible
        with the current environment without actually modifying it.

        Args:
            requirements: List of requirement strings to test

        Returns:
            ResolutionResult with success status and any conflicts
        """
        # Use test_with_additions which creates a temp copy of pyproject.toml
        # and tests the dependencies in isolation
        return self.resolution_tester.test_with_additions(
            base_pyproject=self.pyproject.path,
            additional_deps=requirements,
            group_name=None  # Test as main dependencies for broadest compatibility check
        )

    def _raise_dependency_conflict(
        self,
        node_name: str,
        test_result,
        package_spec: str | None = None,
    ) -> None:
        """Raise enhanced dependency conflict error with actionable suggestions.

        Args:
            node_name: Name of the node being installed
            test_result: ResolutionResult from dependency testing
            package_spec: Package being installed (e.g., "depthflow==0.9.1") for deep analysis
        """
        # Extract conflicting package pairs
        conflict_pairs = extract_conflicting_packages(test_result.stderr)

        # Run deep conflict analysis if possible
        analysis = None
        if package_spec:
            try:
                from ..utils.conflict_analyzer import (
                    analyze_conflict,
                    format_conflict_report,
                )

                venv_python = self.uv.python_executable
                uv_path = Path(self.uv.binary)

                analysis = analyze_conflict(
                    stderr=test_result.stderr,
                    new_package=package_spec,
                    venv_python=venv_python,
                    uv_path=uv_path,
                )

                if analysis:
                    # Log the detailed report for visibility
                    logger.error(format_conflict_report(analysis))
            except Exception as e:
                logger.debug(f"Conflict analysis failed: {e}")

        # Build suggestions (enhanced with analysis if available)
        suggestions = self._build_conflict_suggestions(node_name, analysis)

        # Create enhanced context
        context = DependencyConflictContext(
            node_name=node_name,
            conflicting_packages=conflict_pairs,
            conflict_descriptions=test_result.conflicts,
            raw_stderr=test_result.stderr,
            suggested_actions=suggestions,
            conflict_analysis=analysis,
        )

        raise CDDependencyConflictError(
            f"Cannot add '{node_name}' due to dependency conflicts",
            context=context
        )

    def _build_conflict_suggestions(
        self,
        node_name: str,
        analysis,
    ) -> list[NodeAction]:
        """Build actionable suggestions from conflict analysis.

        Args:
            node_name: Name of the node being installed
            analysis: ConflictAnalysis or None

        Returns:
            List of suggested actions
        """
        suggestions = [
            NodeAction(
                action_type='skip_node',
                description=f"Skip installing '{node_name}'"
            ),
        ]

        # Enhanced suggestions from analysis
        if analysis and analysis.suggestions:
            for suggestion in analysis.suggestions:
                suggestions.append(NodeAction(
                    action_type='add_constraint',
                    description=suggestion
                ))
        else:
            # Fallback suggestion if no analysis
            suggestions.append(NodeAction(
                action_type='add_constraint',
                description="Add version constraint to override (see --verbose for details)"
            ))

        return suggestions

    def _raise_probe_install_failures(self, node_name: str, probe_result) -> None:
        """Raise a dependency conflict when probe couldn't install some requirements.

        Args:
            node_name: Name of the node being installed
            probe_result: ProbeResult from dependency probing
        """
        from ..utils.dependency_probe import ProbeResult

        result: ProbeResult = probe_result

        suggestions = [
            NodeAction(
                action_type="add_node_force",
                node_identifier=node_name,
                description="Install with --no-test flag (skip dependency check)",
            ),
        ]

        context = DependencyConflictContext(
            node_name=node_name,
            conflicting_packages=[],
            conflict_descriptions=[
                f"Probe failed to install requirement: {req}"
                for req in result.install_failures
            ],
            raw_stderr="",
            suggested_actions=suggestions,
        )

        raise CDDependencyConflictError(
            f"Node '{node_name}' dependencies could not be probed (install failures)",
            context=context,
        )

    def _raise_probe_protected_changes(self, node_name: str, probe_result) -> None:
        """Raise a dependency conflict if probe would change protected packages.

        Args:
            node_name: Name of the node being installed
            probe_result: ProbeResult from dependency probing
        """
        from ..utils.dependency_probe import ProbeResult

        result: ProbeResult = probe_result

        suggestions = [
            NodeAction(
                action_type="skip_node",
                description=f"Skip installing '{node_name}'",
            ),
            NodeAction(
                action_type="add_node_force",
                node_identifier=node_name,
                description="Install with --no-test flag (skip dependency check, risk breaking environment)",
            ),
        ]

        context = DependencyConflictContext(
            node_name=node_name,
            conflicting_packages=[(pkg, "") for pkg in result.protected_changes],
            conflict_descriptions=[
                f"Would change protected package: {pkg}" for pkg in result.protected_changes
            ],
            raw_stderr="",
            suggested_actions=suggestions,
        )

        raise CDDependencyConflictError(
            f"Node '{node_name}' would change protected packages: {', '.join(result.protected_changes)}",
            context=context,
        )

    def _validate_constraints_against_environment(
        self,
        node_name: str,
        constraints: list[str],
        requirements: list[str],
    ) -> None:
        """Validate discovered constraints don't conflict with installed packages.

        Uses UV's resolver to check if each constraint is compatible with the
        existing environment. This catches conflicts BEFORE applying constraints.

        Args:
            node_name: Name of the node being installed
            constraints: List of discovered constraints (e.g., ["huggingface_hub<0.37"])
            requirements: Original requirements from the node (for error context)

        Raises:
            CDDependencyConflictError: If any constraint conflicts with installed packages
        """
        from ..utils.conflict_analyzer import (
            check_specifier_compatibility,
            get_existing_requirements,
            parse_constraint_string,
        )

        venv_python = self.uv.python_executable
        uv_path = Path(self.uv.binary)

        for constraint in constraints:
            # Parse the constraint string
            parsed = parse_constraint_string(constraint)
            if not parsed:
                continue

            pkg_name, constraint_spec = parsed
            new_spec = f"{pkg_name}{constraint_spec}"

            # Get existing requirements for this package from the environment
            existing_reqs = get_existing_requirements(pkg_name, venv_python, uv_path)
            if not existing_reqs:
                continue  # No existing requirements, no conflict possible

            # Check each existing requirement for compatibility
            for requiring_pkg, existing_spec in existing_reqs:
                is_compatible, stderr = check_specifier_compatibility(
                    existing_spec, new_spec, venv_python, uv_path
                )

                if not is_compatible:
                    self._raise_constraint_conflict(
                        node_name=node_name,
                        pkg_name=pkg_name,
                        constraint_spec=constraint_spec,
                        requiring_pkg=requiring_pkg,
                        existing_spec=existing_spec,
                        requirements=requirements,
                        stderr=stderr,
                    )

    def _raise_constraint_conflict(
        self,
        node_name: str,
        pkg_name: str,
        constraint_spec: str,
        requiring_pkg: str,
        existing_spec: str,
        requirements: list[str],
        stderr: str,
    ) -> None:
        """Build and raise a detailed conflict error.

        Args:
            node_name: Name of the node being installed
            pkg_name: Normalized name of conflicting package
            constraint_spec: Version specifier from node (e.g., "<0.37")
            requiring_pkg: Package that requires the existing spec
            existing_spec: Full existing requirement (e.g., "huggingface-hub>=1.1.0")
            requirements: Original requirements from the node
            stderr: UV stderr output
        """
        from ..utils.conflict_analyzer import (
            ConflictAnalysis,
            ConflictChain,
            format_conflict_report,
        )

        logger.warning(
            f"Constraint conflict detected: '{pkg_name}{constraint_spec}' "
            f"conflicts with '{requiring_pkg}' which requires '{existing_spec}'"
        )

        analysis = ConflictAnalysis(
            conflicting_package=pkg_name,
            existing_constraints=[(requiring_pkg, existing_spec)],
            new_package_chains=[
                ConflictChain(
                    root_package=requirements[0].split("==")[0] if requirements else node_name,
                    chain=[node_name, "...", pkg_name],
                    constraint=f"{pkg_name}{constraint_spec}",
                    constraint_source="transitive dependency",
                )
            ],
            suggestions=[
                f"The node's dependencies require {pkg_name}{constraint_spec}, "
                f"but {requiring_pkg} requires {existing_spec}",
                "These version ranges have no overlap and cannot be satisfied together",
                f"Consider checking if {requiring_pkg} has a newer version with relaxed constraints",
            ],
        )

        logger.error(format_conflict_report(analysis))

        context = DependencyConflictContext(
            node_name=node_name,
            conflicting_packages=[(pkg_name, requiring_pkg)],
            conflict_descriptions=[
                f"Node requires {pkg_name}{constraint_spec} but {requiring_pkg} requires {existing_spec}"
            ],
            raw_stderr=stderr,
            suggested_actions=[
                NodeAction(
                    action_type='skip_node',
                    description=f"Skip installing '{node_name}'"
                ),
            ],
            conflict_analysis=analysis,
        )

        raise CDDependencyConflictError(
            f"Cannot add '{node_name}': dependency {pkg_name} has conflicting requirements",
            context=context,
        )
