"""Simplified Environment - owns everything about a single ComfyUI environment."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from functools import cached_property, wraps
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit

from ..analyzers.ref_diff_analyzer import RefDiffAnalyzer
from ..analyzers.status_scanner import StatusScanner
from ..factories.uv_factory import create_uv_for_environment
from ..logging.logging_config import get_logger
from ..managers.environment_git_orchestrator import EnvironmentGitOrchestrator
from ..managers.environment_model_manager import EnvironmentModelManager
from ..managers.git_manager import GitManager
from ..managers.model_symlink_manager import ModelSymlinkManager
from ..managers.node_manager import NodeManager
from ..managers.pyproject_manager import PyprojectManager
from ..managers.pytorch_backend_manager import PyTorchBackendManager
from ..managers.system_node_symlink_manager import SystemNodeSymlinkManager
from ..managers.user_content_symlink_manager import UserContentSymlinkManager
from ..managers.uv_project_manager import UVProjectManager
from ..managers.workflow_manager import WorkflowManager
from ..models.environment import EnvironmentStatus
from ..models.ref_diff import RefDiff
from ..models.shared import (
    ManagerStatus,
    ManagerUpdateResult,
    ModelSourceResult,
    ModelSourceStatus,
    NodeDevLinkResult,
    NodeInfo,
    NodeRemovalResult,
    UpdateResult,
)
from ..models.sync import SyncResult
from ..strategies.confirmation import ConfirmationStrategy
from ..utils.common import run_command
from ..utils.environment_lock import EnvironmentOperationLock
from ..utils.filesystem import rmtree
from ..utils.node_identity import resolve_installed_node_alias
from ..validation.resolution_tester import ResolutionTester

if TYPE_CHECKING:
    from comfygit_core.core.workspace import Workspace
    from comfygit_core.models.protocols import (
        ExportCallbacks,
        ImportCallbacks,
        ModelResolutionStrategy,
        NodeResolutionStrategy,
        RollbackStrategy,
        SyncCallbacks,
    )

    from ..caching.workflow_cache import WorkflowCacheRepository
    from ..models.dependency_resolution import (
        DependencyResolutionAcceptance,
        DependencyResolutionApplyResult,
        DependencyResolutionPreview,
    )
    from ..models.manifest import EnvironmentManifestSnapshot
    from ..models.merge_plan import MergeResult, MergeValidation
    from ..models.workflow import (
        BatchDownloadCallbacks,
        DetailedWorkflowStatus,
        NodeInstallCallbacks,
        ResolutionResult,
        WorkflowSyncStatus,
    )
    from ..models.workflow_contract import WorkflowExecutionContract
    from ..services.node_lookup_service import NodeLookupService

logger = get_logger(__name__)


def _workflow_api_prompt_relpath(workflow_name: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", workflow_name).strip()
    safe_name = safe_name or "workflow"
    return Path("workflow_api") / f"{safe_name}.api.json"


def _requires_env_lock(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._operation_lock:
            return method(self, *args, **kwargs)
    return wrapper


class Environment:
    """A ComfyUI environment - manages its own state through pyproject.toml."""

    def __init__(
        self,
        name: str,
        path: Path,
        workspace: Workspace,
        torch_backend: str | None = None,
    ):
        self.name = name
        self.path = path
        self.workspace = workspace
        self.torch_backend = torch_backend

        # Workspace-level paths
        self.workspace_paths = workspace.paths
        self.global_models_path = workspace.workspace_config_manager.get_models_directory()

        # Workspace-level services
        self.model_repository = workspace.model_repository
        self.node_mapping_repository = workspace.node_mapping_repository
        self.comfyui_builtin_versions_repository = (
            workspace.comfyui_builtin_versions_repository
        )
        self.workspace_config_manager = workspace.workspace_config_manager
        self.model_downloader = workspace.model_downloader

        # Core paths
        self.cec_path = path / ".cec"
        self.pyproject_path = self.cec_path / "pyproject.toml"
        self.comfyui_path = path / "ComfyUI"
        self.custom_nodes_path = self.comfyui_path / "custom_nodes"
        self.venv_path = path / ".venv"
        self.models_path = self.comfyui_path / "models"

        # Guard against concurrent mutations of this environment.
        self._operation_lock = EnvironmentOperationLock(self.path / ".comfygit.lock")

    ## Cached properties ##
    #
    # Orchestrators coordinate git and model operations with environment state:
    # - git_orchestrator: Wraps git operations with node reconciliation + package sync + workflow restore
    # - model_manager: Coordinates model operations across pyproject, repository, and downloader
    #
    # This pattern keeps environment.py thin by delegating complex multi-step operations.

    @cached_property
    def uv_manager(self) -> UVProjectManager:
        return create_uv_for_environment(
            self.workspace_paths.root,
            cec_path=self.cec_path,
            venv_path=self.venv_path,
            torch_backend=self.torch_backend,
            external_uv_cache=self.workspace_config_manager.get_external_uv_cache(),
        )

    @cached_property
    def pyproject(self) -> PyprojectManager:
        return PyprojectManager(self.pyproject_path)

    @cached_property
    def pytorch_manager(self) -> PyTorchBackendManager:
        return PyTorchBackendManager(self.cec_path)

    @cached_property
    def overlay_manager(self):
        """Overlay manager bound to this environment's UV manager."""
        return self.uv_manager.overlay_manager

    @cached_property
    def node_lookup(self) -> NodeLookupService:
        from ..services.node_lookup_service import NodeLookupService
        return NodeLookupService(
            cache_path=self.workspace_paths.cache,
            node_mappings_repository=self.node_mapping_repository,
            workspace_config=self.workspace_config_manager,
        )

    @cached_property
    def resolution_tester(self) -> ResolutionTester:
        return ResolutionTester(self.workspace_paths.root)

    @cached_property
    def package_config(self):
        """Get package configuration manager for substitutions and exclusions."""
        from ..configs.package_config import PackageConfigManager
        return PackageConfigManager(self.cec_path)

    def get_sync_extras(self) -> list[str]:
        """Get default optional extras installed during sync."""
        return self.pyproject.get_sync_extras()

    def add_sync_extra(self, extra: str) -> bool:
        """Add a default optional extra (returns True if added)."""
        return self.pyproject.add_sync_extra(extra)

    def remove_sync_extra(self, extra: str) -> bool:
        """Remove a default optional extra (returns True if removed)."""
        return self.pyproject.remove_sync_extra(extra)

    @cached_property
    def node_manager(self) -> NodeManager:
        return NodeManager(
            self.pyproject,
            self.uv_manager,
            self.node_lookup,
            self.resolution_tester,
            self.custom_nodes_path,
            self.node_mapping_repository,
            self.pytorch_manager,
            self.package_config,
        )

    @cached_property
    def model_symlink_manager(self) -> ModelSymlinkManager:
        """Get model symlink manager."""
        return ModelSymlinkManager(
            self.comfyui_path, self.global_models_path
        )

    @cached_property
    def user_content_manager(self) -> UserContentSymlinkManager:
        """Get user content symlink manager for input/output directories."""
        return UserContentSymlinkManager(
            self.comfyui_path,
            self.name,
            self.workspace_paths.input,
            self.workspace_paths.output,
        )

    @cached_property
    def system_node_manager(self) -> SystemNodeSymlinkManager:
        """Get system node symlink manager for workspace-level infrastructure nodes."""
        return SystemNodeSymlinkManager(
            self.comfyui_path,
            self.workspace_paths.system_nodes,
        )

    @cached_property
    def workflow_cache(self) -> WorkflowCacheRepository:
        """Get workflow cache repository."""
        from ..caching.workflow_cache import WorkflowCacheRepository
        cache_db_path = self.workspace_paths.cache / "workflows.db"
        return WorkflowCacheRepository(
            cache_db_path,
            pyproject_manager=self.pyproject,
            model_repository=self.model_repository,
            workspace_config_manager=self.workspace_config_manager
        )

    @cached_property
    def workflow_manager(self) -> WorkflowManager:
        return WorkflowManager(
            self.comfyui_path,
            self.cec_path,
            self.pyproject,
            self.model_repository,
            self.node_mapping_repository,
            self.model_downloader,
            self.workflow_cache,
            self.name,
            builtin_versions_repository=self.comfyui_builtin_versions_repository,
        )

    @cached_property
    def git_manager(self) -> GitManager:
        return GitManager(self.cec_path)

    @cached_property
    def git_orchestrator(self) -> EnvironmentGitOrchestrator:
        """Get environment-aware git orchestrator."""
        return EnvironmentGitOrchestrator(
            git_manager=self.git_manager,
            node_manager=self.node_manager,
            pyproject_manager=self.pyproject,
            uv_manager=self.uv_manager,
            workflow_manager=self.workflow_manager,
            pytorch_manager=self.pytorch_manager,
        )

    @cached_property
    def model_manager(self) -> EnvironmentModelManager:
        """Get environment model manager."""
        return EnvironmentModelManager(
            pyproject=self.pyproject,
            model_repository=self.model_repository,
            model_downloader=self.model_downloader,
        )

    ## Helper methods ##

    ## Public methods ##

    # =====================================================
    # Environment Management
    # =====================================================

    def status(self) -> EnvironmentStatus:
        """Get environment sync and git status."""
        # Each subsystem provides its complete status
        scanner = StatusScanner(
            comfyui_path=self.comfyui_path,
            venv_path=self.venv_path,
            uv=self.uv_manager,
            pyproject=self.pyproject,
            pytorch_manager=self.pytorch_manager,
        )
        comparison = scanner.get_full_comparison()

        git_status = self.git_manager.get_status(self.pyproject)

        workflow_status = self.workflow_manager.get_workflow_status()

        # Detect missing models
        missing_models = self.model_manager.detect_missing_models()

        # Assemble final status
        return EnvironmentStatus.create(
            comparison=comparison,
            git_status=git_status,
            workflow_status=workflow_status,
            missing_models=missing_models
        )

    def get_manager_status(self) -> ManagerStatus:
        """Check current comfygit-manager installation status.

        Returns ManagerStatus with:
        - current_version: Version from pyproject.toml or detected from filesystem
        - latest_version: Latest version from ComfyUI Registry
        - update_available: Whether latest > current
        - is_legacy: True if manager is symlinked (legacy workspace)
        - is_tracked: True if manager is tracked in pyproject.toml
        - status: "headless", "legacy", "not_installed", "outdated", or "up_to_date"
        """
        from packaging.version import InvalidVersion, Version

        from ..constants import MANAGER_NODE_ID
        from ..utils.symlink_utils import is_link

        # Explicit headless marker takes precedence over manager install checks.
        if self._is_headless_mode():
            return ManagerStatus(
                current_version=None,
                latest_version=None,
                update_available=False,
                is_legacy=False,
                is_tracked=False,
                status="headless",
            )

        current_version: str | None = None
        is_legacy = False
        is_tracked = False

        # First check if tracked in pyproject (modern per-env manager)
        nodes = self.pyproject.nodes.get_existing()
        if MANAGER_NODE_ID in nodes:
            is_tracked = True
            current_version = nodes[MANAGER_NODE_ID].version
        else:
            # Not tracked - check for legacy symlink at registry ID path
            legacy_path = self.custom_nodes_path / MANAGER_NODE_ID
            if is_link(legacy_path):
                is_legacy = True
                # Try to read version from symlink target
                try:
                    import tomllib
                    target_pyproject = legacy_path / "pyproject.toml"
                    if target_pyproject.exists():
                        with open(target_pyproject, "rb") as f:
                            data = tomllib.load(f)
                            current_version = data.get("project", {}).get("version")
                except Exception:
                    pass

        # Get latest version from registry
        latest_version: str | None = None
        try:
            node_info = self.node_lookup.get_node(MANAGER_NODE_ID)
            if node_info:
                latest_version = node_info.version
        except Exception:
            # Registry lookup failed - continue without latest
            pass

        # Determine if update is available
        update_available = False
        if current_version and latest_version:
            try:
                update_available = Version(latest_version) > Version(current_version)
            except InvalidVersion:
                # Version comparison failed - assume update available if versions differ
                update_available = latest_version != current_version

        status_name = "up_to_date"
        if is_legacy:
            status_name = "legacy"
        elif not is_tracked:
            status_name = "not_installed"
        elif update_available:
            status_name = "outdated"

        return ManagerStatus(
            current_version=current_version,
            latest_version=latest_version,
            update_available=update_available,
            is_legacy=is_legacy,
            is_tracked=is_tracked,
            status=status_name,
        )

    @_requires_env_lock
    def update_manager(
        self,
        version: str = "latest",
        confirmation_strategy: ConfirmationStrategy | None = None,
    ) -> ManagerUpdateResult:
        """Update comfygit-manager with migration support.

        Handles:
        1. Legacy symlink → tracked node migration
        2. Cleanup of dependency-groups.system-nodes
        3. Standard registry node update flow
        4. Schema version bump on first migration

        Args:
            version: Target version ("latest" or specific version)
            confirmation_strategy: Strategy for confirming changes

        Returns:
            ManagerUpdateResult with details of what changed
        """
        from ..constants import MANAGER_NODE_ID
        from ..utils.symlink_utils import is_link

        manager_path = self.custom_nodes_path / MANAGER_NODE_ID
        status = self.get_manager_status()

        # Ensure PyTorch backend is configured (auto-probe if missing)
        python_version_file = self.cec_path / ".python-version"
        python_version = (
            python_version_file.read_text(encoding="utf-8").strip()
            if python_version_file.exists()
            else "3.12"
        )
        self.pytorch_manager.ensure_backend(python_version)

        old_version = status.current_version
        was_migration = False

        # Handle legacy symlink migration
        if status.is_legacy:
            # Remove symlink - we'll install fresh
            if is_link(manager_path):
                manager_path.unlink()
            was_migration = True

        # Check if already tracked
        nodes = self.pyproject.nodes.get_existing()
        if MANAGER_NODE_ID in nodes and not was_migration:
            # Standard update flow, optionally pinned to a caller-selected version.
            result = self.node_manager.update_node(
                MANAGER_NODE_ID,
                confirmation_strategy=confirmation_strategy,
                target_version=None if version == "latest" else version,
            )

            # Cleanup legacy dependency group if present
            self._cleanup_system_nodes_dependency_group()
            self._clear_headless_marker()

            return ManagerUpdateResult(
                changed=result.changed,
                was_migration=False,
                old_version=result.old_version,
                new_version=result.new_version,
                message=result.message,
            )

        # Not tracked or migrating - add as new node
        node_info = self.node_manager.add_node(
            identifier=MANAGER_NODE_ID if version == "latest" else f"{MANAGER_NODE_ID}@{version}",
        )

        # Cleanup legacy dependency group
        self._cleanup_system_nodes_dependency_group()
        self._clear_headless_marker()

        # Bump workspace schema if this was a migration
        if was_migration and self.workspace.is_legacy_schema():
            self.workspace._write_schema_version()

        return ManagerUpdateResult(
            changed=True,
            was_migration=was_migration,
            old_version=old_version,
            new_version=node_info.version,
            message="Migrated to per-environment manager" if was_migration else f"Installed {MANAGER_NODE_ID}",
        )

    def _cleanup_system_nodes_dependency_group(self) -> None:
        """Remove legacy dependency-groups.system-nodes from pyproject.toml."""
        config = self.pyproject.load()
        dep_groups = config.get("dependency-groups", {})
        if "system-nodes" in dep_groups:
            del dep_groups["system-nodes"]
            if not dep_groups:
                del config["dependency-groups"]
            self.pyproject.save(config)
            logger.info("Removed legacy dependency-groups.system-nodes")

    def _is_headless_mode(self) -> bool:
        """Return True when this environment was created/imported with --no-manager."""
        config = self.pyproject.load()
        return bool(config.get("tool", {}).get("comfygit", {}).get("headless", False))

    def _set_headless_marker(self) -> None:
        """Persist headless marker in pyproject.toml."""
        config = self.pyproject.load()
        self._set_comfygit_scalar(config, "headless", True)
        self.pyproject.save(config)

    def _set_comfygit_scalar(self, config: dict, key: str, value: object) -> None:
        """Set a scalar on [tool.comfygit] before child tables.

        TOML requires table values to appear before child tables such as
        [tool.comfygit.nodes.*]. TOMLKit can silently drop scalars appended
        after those child tables, so rebuild this table in a valid order.
        """
        tool = config.setdefault("tool", {})
        comfygit_cfg = tool.setdefault("comfygit", {})
        rebuilt = tomlkit.table()
        child_items: list[tuple[str, object]] = []

        for existing_key, existing_value in comfygit_cfg.items():
            if existing_key == key:
                continue
            if isinstance(existing_value, dict):
                child_items.append((existing_key, existing_value))
            else:
                rebuilt[existing_key] = existing_value

        rebuilt[key] = value
        for child_key, child_value in child_items:
            rebuilt[child_key] = child_value

        tool["comfygit"] = rebuilt

    def _prepare_headless_import(self) -> None:
        """Prepare imported/materialized environments that should not load Manager."""
        from ..constants import MANAGER_NODE_ID

        if self.pyproject.nodes.remove(MANAGER_NODE_ID):
            logger.info("Removed comfygit-manager from headless environment manifest")
        self._set_headless_marker()

    def _clear_headless_marker(self) -> None:
        """Remove headless marker after manager installation."""
        config = self.pyproject.load()
        comfygit_cfg = config.get("tool", {}).get("comfygit", {})
        if comfygit_cfg.get("headless"):
            del comfygit_cfg["headless"]
            self.pyproject.save(config)

    def _register_imported_manager(self) -> None:
        """Auto-register or install comfygit-manager for imported environment.

        Order of operations:
        1. If tracked in pyproject.toml → already good, skip
        2. If directory exists (from export) → register with detected version
        3. If missing entirely → install fresh from registry

        This replaces the legacy symlink system where manager was symlinked from
        workspace-level .metadata/system_nodes/.
        """
        from ..constants import MANAGER_NODE_ID

        # Check if already tracked
        nodes = self.pyproject.nodes.get_existing()
        if MANAGER_NODE_ID in nodes:
            logger.debug("comfygit-manager already tracked in pyproject.toml")
            return

        manager_path = self.custom_nodes_path / MANAGER_NODE_ID

        if manager_path.exists() and manager_path.is_dir():
            # Directory exists - register from filesystem
            self._register_existing_manager(manager_path)
        else:
            # Not present - install fresh from registry
            self._install_manager_from_registry()

        # Always cleanup legacy dependency group
        self._cleanup_system_nodes_dependency_group()

    def _register_existing_manager(self, manager_path: Path) -> None:
        """Register existing manager directory in pyproject.toml."""
        import tomllib

        from ..constants import MANAGER_NODE_ID

        # Detect version from manager's pyproject.toml
        version = None
        manager_pyproject = manager_path / "pyproject.toml"
        if manager_pyproject.exists():
            try:
                with open(manager_pyproject, "rb") as f:
                    data = tomllib.load(f)
                    version = data.get("project", {}).get("version")
            except Exception as e:
                logger.warning(f"Could not read manager version: {e}")

        # Register as tracked node
        config = self.pyproject.load()
        if "tool" not in config:
            config["tool"] = {}
        if "comfygit" not in config["tool"]:
            config["tool"]["comfygit"] = {}
        if "nodes" not in config["tool"]["comfygit"]:
            config["tool"]["comfygit"]["nodes"] = {}

        config["tool"]["comfygit"]["nodes"][MANAGER_NODE_ID] = {
            "name": MANAGER_NODE_ID,
            "version": version or "unknown",
            "source": "registry",
            "registry_id": MANAGER_NODE_ID,
        }
        self.pyproject.save(config)
        logger.info(f"Registered existing comfygit-manager (v{version or 'unknown'})")

    def _install_manager_from_registry(self) -> None:
        """Install comfygit-manager from registry during import."""
        from ..constants import MANAGER_NODE_ID

        logger.info("Installing comfygit-manager from registry...")
        try:
            self.node_manager.add_node(MANAGER_NODE_ID)
            logger.info("comfygit-manager installed successfully")

            # Upgrade workspace schema if this is a legacy workspace
            if self.workspace.upgrade_schema_if_needed():
                logger.info("Upgraded workspace to schema v2")
        except Exception as e:
            # Manager installation failure is non-fatal
            logger.warning(f"Could not install comfygit-manager: {e}")
            logger.warning("Environment will work but manager panel will be unavailable")

    def _ensure_schema_migrated(self) -> bool:
        """Migrate pyproject schema v1 → v2 if needed.

        Schema v1 has PyTorch config embedded in [tool.uv] section.
        Schema v2 uses runtime injection from .pytorch-backend file.

        This migration:
        1. Strips embedded [tool.uv] PyTorch config
        2. Updates schema_version to 2

        Note: Does NOT persist .pytorch-backend. User must explicitly
        set backend with 'cg env-config torch-backend set'.

        Returns:
            True if migration was performed, False if already migrated
        """
        migrated = self.pyproject.migrate_pytorch_config()
        if migrated:
            logger.info("Migrated environment to schema v2 (stripped PyTorch config)")
            # Print so user sees it in CLI output
            import sys
            print("📦 Migrated environment to schema v2 (stripped embedded PyTorch config)", file=sys.stderr)

        # Always ensure .pytorch-backend and uv.lock are in .gitignore (handles pulls from older remotes)
        self.pytorch_manager._ensure_gitignore_entry()
        self.git_manager.ensure_gitignore_entry("uv.lock")
        self.git_manager.ensure_gitignore_entry("backups/")
        self.git_manager.ensure_gitignore_entry("comfyui_builtins.json")
        self.git_manager.ensure_gitignore_entry("comfyui_folder_paths.json")
        self.git_manager.ensure_gitignore_entry("comfyui_model_loaders.json")
        self._untrack_uvlock_if_tracked()
        self._untrack_generated_metadata_if_tracked()

        return migrated

    @_requires_env_lock
    def sync(
        self,
        dry_run: bool = False,
        model_strategy: str = "skip",
        model_callbacks: BatchDownloadCallbacks | None = None,
        node_callbacks: NodeInstallCallbacks | None = None,
        remove_extra_nodes: bool = True,
        sync_callbacks: SyncCallbacks | None = None,
        verbose: bool = False,
        preserve_workflows: bool = False,
        backend_override: str | None = None,
        overlay_names: list[str] | None = None,
        extras: list[str] | None = None,
        all_extras: bool = False,
    ) -> SyncResult:
        """Apply changes: sync packages, nodes, workflows, and models with environment.

        Args:
            dry_run: If True, don't actually apply changes
            model_strategy: Model download strategy - "all", "required", or "skip" (default: skip)
            model_callbacks: Optional callbacks for model download progress
            node_callbacks: Optional callbacks for node installation progress
            remove_extra_nodes: If True, remove extra nodes. If False, only warn (default: True)
            verbose: If True, show uv output in real-time during dependency installation
            preserve_workflows: If True, preserve uncommitted workflows during restore.
                               Use True for runtime restarts (exit code 42) to keep user edits.
                               Use False (default) for git operations and repairs.
            backend_override: Override PyTorch backend instead of reading from file (e.g., "cu128")
            overlay_names: One-time overlay names for this sync call.
            extras: Optional list of extras to install
            all_extras: Install all optional extras

        Returns:
            SyncResult with details of what was synced

        Raises:
            UVCommandError: If sync fails
        """
        result = SyncResult()

        # Migrate schema v1 → v2 if needed (strips embedded PyTorch config)
        # This ensures old environments get migrated on first sync with new code
        self._ensure_schema_migrated()

        # Ensure package config exists (migration for existing envs)
        self.package_config.ensure_exists()

        # Sync exclude-dependencies from package_config.toml to pyproject.toml
        # This ensures user edits to package_config.toml take effect
        self.pyproject.uv_config.set_exclude_dependencies(
            self.package_config.exclude_packages
        )
        self.pyproject.ensure_system_uv_dependency()

        extras, all_extras = self.pyproject.resolve_sync_extras(extras, all_extras)

        logger.info("Syncing environment...")

        # Sync packages with UV - progressive installation with PyTorch injection
        try:
            sync_result = self.uv_manager.sync_dependencies_progressive(
                dry_run=dry_run,
                callbacks=sync_callbacks,
                verbose=verbose,
                pytorch_manager=self.pytorch_manager,
                overlay_names=overlay_names,
                backend_override=backend_override,
                extras=extras,
                all_extras=all_extras,
            )
            result.packages_synced = sync_result["packages_synced"]
            result.dependency_groups_installed.extend(sync_result["dependency_groups_installed"])
            result.dependency_groups_failed.extend(sync_result["dependency_groups_failed"])
        except Exception as e:
            # Progressive sync handles optional groups gracefully
            # Only base or required groups cause this exception
            logger.error(f"Package sync failed: {e}")
            result.errors.append(f"Package sync failed: {e}")
            result.success = False

        # Handle version mismatches by removing nodes with wrong versions
        # They will be reinstalled by sync_nodes_to_filesystem
        if not dry_run:
            try:
                # Get current status to find version mismatches
                current_status = self.status()
                for mismatch in current_status.comparison.version_mismatches:
                    node_name = mismatch['name']
                    node_path = self.custom_nodes_path / node_name
                    if node_path.exists():
                        logger.info(f"Removing node with wrong version: {node_name} ({mismatch['actual']} → {mismatch['expected']})")
                        rmtree(node_path)
            except Exception as e:
                logger.warning(f"Could not check/fix version mismatches: {e}")

        # Sync custom nodes to filesystem
        try:
            # Pass remove_extra flag (default True for aggressive repair behavior)
            self.node_manager.sync_nodes_to_filesystem(
                remove_extra=remove_extra_nodes and not dry_run,
                callbacks=node_callbacks
            )
            # For now, we just note it happened
        except Exception as e:
            logger.error(f"Node sync failed: {e}")
            result.errors.append(f"Node sync failed: {e}")
            result.success = False

        staged_node_groups: list[str] = []
        if not dry_run:
            try:
                staged_node_groups = self.node_manager.provision_missing_node_dependencies()
                if staged_node_groups:
                    logger.info(
                        "Syncing %d staged node dependency group(s)",
                        len(staged_node_groups),
                    )
                    self.uv_manager.sync_project(
                        verbose=verbose,
                        pytorch_manager=self.pytorch_manager,
                        overlay_names=overlay_names,
                        backend_override=backend_override,
                        extras=extras,
                        all_extras=all_extras,
                        all_groups=True,
                    )
                    result.dependency_groups_installed.extend(staged_node_groups)
            except Exception as e:
                logger.error(f"Node dependency provisioning failed: {e}")
                result.errors.append(f"Node dependency provisioning failed: {e}")
                result.dependency_groups_failed.extend(
                    (group_name, str(e)) for group_name in staged_node_groups
                )
                result.success = False

        # Restore workflows from .cec/ to ComfyUI (for git pull workflow)
        if not dry_run and not preserve_workflows:
            logger.debug("Restoring workflows from .cec/")
            try:
                self.workflow_manager.restore_all_from_cec()
                logger.info("Restored workflows from .cec/")
            except Exception as e:
                logger.warning(f"Failed to restore workflows: {e}")
                result.errors.append(f"Workflow restore failed: {e}")
                # Non-fatal - continue

        # Handle missing models
        if not dry_run and model_strategy != "skip":
            try:
                # Reuse existing import machinery
                workflows_with_intents = self.model_manager.prepare_import_with_model_strategy(
                    strategy=model_strategy
                )

                if workflows_with_intents:
                    logger.info(f"Downloading models for {len(workflows_with_intents)} workflow(s)")

                    # prepare_import_with_model_strategy() may update pyproject model entries.
                    # Invalidate per-workflow cache entries so resolve_workflow() sees fresh
                    # download intents instead of stale session-cached resolutions.
                    for workflow_name in workflows_with_intents:
                        self.workflow_cache.invalidate(self.name, workflow_name)

                    # Resolve each workflow (triggers downloads)
                    from ..strategies.auto import AutoModelStrategy, AutoNodeStrategy

                    for workflow_name in workflows_with_intents:
                        try:
                            logger.debug(f"Resolving workflow: {workflow_name}")

                            # Resolve workflow (analyzes and prepares downloads)
                            resolution_result = self.resolve_workflow(
                                name=workflow_name,
                                model_strategy=AutoModelStrategy(),
                                node_strategy=AutoNodeStrategy(),
                                download_callbacks=model_callbacks
                            )

                            # Track downloads from actual download results (not stale ResolvedModel objects)
                            # Note: Download results are populated by _execute_pending_downloads() during resolve_workflow()
                            for dr in resolution_result.download_results:
                                if dr.success:
                                    result.models_downloaded.append(dr.filename)
                                else:
                                    result.models_failed.append((dr.filename, dr.error or "Download failed"))

                        except Exception as e:
                            logger.error(f"Failed to resolve {workflow_name}: {e}", exc_info=True)
                            result.errors.append(f"Failed to resolve {workflow_name}: {e}")

            except Exception as e:
                logger.warning(f"Model download failed: {e}", exc_info=True)
                result.errors.append(f"Model download failed: {e}")
                # Non-fatal - continue

        # Ensure model symlink exists
        try:
            self.model_symlink_manager.create_symlink()
            result.model_paths_configured = True
        except Exception as e:
            logger.warning(f"Failed to ensure model symlink: {e}")
            result.errors.append(f"Model symlink configuration failed: {e}")
            # Continue anyway - symlink might already exist from environment creation

        # Auto-migrate existing environments (one-time operation)
        # Check if input/output are real directories with content
        needs_migration = False
        if self.comfyui_path.exists():
            from ..utils.symlink_utils import is_link

            input_path = self.comfyui_path / "input"
            output_path = self.comfyui_path / "output"

            if input_path.exists() and not is_link(input_path):
                needs_migration = True
            if output_path.exists() and not is_link(output_path):
                needs_migration = True

        if needs_migration:
            logger.info("Detected pre-symlink environment, migrating user data...")
            try:
                migration_stats = self.user_content_manager.migrate_existing_data()
                total_moved = (
                    migration_stats["input_files_moved"] +
                    migration_stats["output_files_moved"]
                )
                if total_moved > 0:
                    logger.info(
                        f"Migration complete: {total_moved} files moved to workspace-level storage"
                    )
            except Exception as e:
                logger.error(f"Migration failed: {e}")
                result.errors.append(f"User data migration failed: {e}")
                # Don't fail sync - user can migrate manually

        # Ensure user content symlinks exist
        try:
            self.user_content_manager.create_directories()
            self.user_content_manager.create_symlinks()
            logger.debug("User content symlinks configured")
        except Exception as e:
            logger.warning(f"Failed to ensure user content symlinks: {e}")
            result.errors.append(f"User content symlink configuration failed: {e}")
            # Continue anyway - symlinks might already exist

        # Mark environment as complete after successful sync (repair operation)
        # This ensures environments that lost .complete (e.g., from manual git pull) are visible
        if result.success and not dry_run:
            from ..utils.environment_cleanup import mark_environment_complete
            mark_environment_complete(self.cec_path)
            logger.debug("Marked environment as complete")

        if result.success:
            logger.info("Successfully synced environment")
        else:
            logger.warning(f"Sync completed with {len(result.errors)} errors")

        return result

    # =====================================================
    # Pull/Merge Preview
    # =====================================================

    def preview_pull(
        self,
        remote: str = "origin",
        branch: str | None = None,
    ) -> RefDiff:
        """Preview what changes a pull operation would bring.

        Fetches from remote and compares to show what nodes, models,
        workflows, and dependencies would change.

        Args:
            remote: Remote name (default: origin)
            branch: Branch to pull (default: current branch)

        Returns:
            RefDiff showing all changes

        Raises:
            ValueError: If remote branch doesn't exist
        """
        from ..utils.git import git_fetch, git_get_current_branch, git_rev_parse

        # Fetch to update remote refs
        git_fetch(self.cec_path, remote)

        # Determine target ref
        current_branch = branch or git_get_current_branch(self.cec_path)
        target_ref = f"{remote}/{current_branch}"

        # Check if remote branch exists
        if not git_rev_parse(self.cec_path, target_ref):
            raise ValueError(
                f"Remote branch '{target_ref}' doesn't exist.\n"
                f"The remote '{remote}' may not have a branch named '{current_branch}'.\n"
                f"  • Check available branches: git branch -r\n"
                f"  • Push this branch first: cg push -r {remote}"
            )

        # Analyze diff
        analyzer = RefDiffAnalyzer(self.cec_path)
        return analyzer.analyze(base_ref="HEAD", target_ref=target_ref)

    def preview_merge(self, branch: str) -> RefDiff:
        """Preview what changes merging a branch would bring.

        Args:
            branch: Branch to merge

        Returns:
            RefDiff showing all changes and conflicts
        """
        analyzer = RefDiffAnalyzer(self.cec_path)
        return analyzer.analyze(base_ref="HEAD", target_ref=branch, detect_conflicts=True)

    @_requires_env_lock
    def pull_and_repair(
        self,
        remote: str = "origin",
        branch: str | None = None,
        model_strategy: str = "all",
        model_callbacks: BatchDownloadCallbacks | None = None,
        node_callbacks: NodeInstallCallbacks | None = None,
        strategy_option: str | None = None,
        force: bool = False,
        backend_override: str | None = None,
    ) -> dict:
        """Pull from remote and auto-repair environment (atomic operation).

        If sync fails, git changes are rolled back automatically.
        This ensures the environment is never left in a half-pulled state.

        Args:
            remote: Remote name (default: origin)
            branch: Branch to pull (default: current)
            model_strategy: Model download strategy ("all", "required", "skip")
            model_callbacks: Optional callbacks for model download progress
            node_callbacks: Optional callbacks for node installation progress
            strategy_option: Optional git merge strategy (e.g., "ours" or "theirs")
            force: If True, discard uncommitted changes and allow unrelated histories
            backend_override: Override PyTorch backend for sync (e.g., "cu128")

        Returns:
            Dict with pull results and sync_result

        Raises:
            CDEnvironmentError: If uncommitted changes exist (without force) or sync fails
            ValueError: If merge conflicts
            OSError: If pull or repair fails
        """
        from ..models.exceptions import CDEnvironmentError
        from ..utils.git import git_reset_hard, git_rev_parse

        # Check for uncommitted changes
        if self.git_manager.has_uncommitted_changes():
            if force:
                # Force mode: discard uncommitted changes
                logger.warning("Force mode: discarding uncommitted changes")
                self.git_manager.reset_to("HEAD", mode="hard")
            else:
                raise CDEnvironmentError(
                    "Cannot pull with uncommitted changes.\n"
                    "  • Commit: cg commit -m 'message'\n"
                    "  • Discard: cg reset --hard\n"
                    "  • Force: cg pull origin --force"
                )

        # Capture pre-pull state for atomic rollback
        pre_pull_commit = git_rev_parse(self.cec_path, "HEAD")
        if not pre_pull_commit:
            raise CDEnvironmentError(
                "Cannot determine current commit state.\n"
                "The .cec repository may be corrupted. Try:\n"
                "  • Check git status: cd .cec && git status\n"
                "  • Repair repository: cd .cec && git fsck"
            )

        try:
            # Determine branch
            from ..utils.git import git_fetch, git_get_current_branch
            current_branch = branch or git_get_current_branch(self.cec_path)
            target_ref = f"{remote}/{current_branch}"

            if force:
                # Force mode: completely replace local with remote (no merge, no conflicts)
                logger.info(f"Force pulling - resetting to {target_ref}...")
                git_fetch(self.cec_path, remote)
                git_reset_hard(self.cec_path, target_ref)
                pull_result = {
                    'fetch_output': '',
                    'merge_output': f'Reset to {target_ref}',
                    'branch': current_branch,
                }
            else:
                # Normal pull (fetch + merge)
                logger.info("Pulling from remote...")
                pull_result = self.git_manager.pull(remote, branch, strategy_option=strategy_option)

            # Auto-repair (restores workflows, installs nodes, downloads models)
            logger.info("Syncing environment after pull...")
            sync_result = self.sync(
                model_strategy=model_strategy,
                model_callbacks=model_callbacks,
                node_callbacks=node_callbacks,
                backend_override=backend_override,
            )

            # Check for sync failures
            if not sync_result.success:
                logger.error("Sync failed - rolling back git changes")
                git_reset_hard(self.cec_path, pre_pull_commit)
                raise CDEnvironmentError(
                    "Sync failed after pull. Git changes rolled back.\n"
                    f"Errors: {', '.join(sync_result.errors)}"
                )

            # Return both pull result and sync result for CLI to display
            return {
                **pull_result,
                'sync_result': sync_result
            }

        except Exception as e:
            # Any failure during sync - rollback git changes
            # (merge conflicts raise before this point, so don't rollback those)
            if "Merge conflict" not in str(e):
                logger.error(f"Pull failed: {e} - rolling back git changes")
                git_reset_hard(self.cec_path, pre_pull_commit)
            raise

    @_requires_env_lock
    def push_commits(self, remote: str = "origin", branch: str | None = None, force: bool = False) -> str:
        """Push commits to remote (requires clean working directory).

        Args:
            remote: Remote name (default: origin)
            branch: Branch to push (default: current)
            force: Use --force-with-lease for force push (default: False)

        Returns:
            Push output

        Raises:
            CDEnvironmentError: If uncommitted changes exist
            ValueError: If no remote or detached HEAD
            OSError: If push fails
        """
        from ..models.exceptions import CDEnvironmentError

        # Check for uncommitted git changes (not workflow sync state)
        # Push only cares about git state in .cec/, not whether workflows are synced to ComfyUI
        if self.git_manager.has_uncommitted_changes():
            raise CDEnvironmentError(
                "Cannot push with uncommitted changes.\n"
                "  Run: cg commit -m 'message' first"
            )

        from ..services.environment_readiness import collect_contract_artifact_blockers

        contract_artifact_issues = collect_contract_artifact_blockers(self)
        if contract_artifact_issues:
            details = [
                detail
                for issue in contract_artifact_issues
                for detail in issue.details
            ]
            detail_text = "\n".join(f"  • {detail}" for detail in details)
            raise CDEnvironmentError(
                "Cannot push with missing or invalid workflow contract API prompt files.\n"
                f"{detail_text}\n"
                "  Re-save the affected contract in ComfyGit Manager, then commit again."
            )

        # Note: Workflow issue validation happens during commit (execute_commit checks is_commit_safe).
        # By the time we reach push, all committed changes have already been validated.
        # No need to re-check workflow issues here.

        # Push
        logger.info("Pushing commits to remote...")
        return self.git_manager.push(remote, branch, force=force)

    @_requires_env_lock
    def checkout(
        self,
        ref: str,
        strategy: RollbackStrategy | None = None,
        force: bool = False
    ) -> None:
        """Checkout commit/branch without auto-committing.

        Args:
            ref: Git reference (commit hash, branch, tag)
            strategy: Optional strategy for confirming destructive checkout
            force: If True, discard uncommitted changes without confirmation

        Raises:
            ValueError: If ref doesn't exist
            CDEnvironmentError: If uncommitted changes exist and no strategy/force
        """
        self.git_orchestrator.checkout(ref, strategy, force)

    @_requires_env_lock
    def reset(
        self,
        ref: str | None = None,
        mode: str = "hard",
        strategy: RollbackStrategy | None = None,
        force: bool = False
    ) -> None:
        """Reset HEAD to ref with git reset semantics.

        Args:
            ref: Git reference to reset to (None = HEAD)
            mode: Reset mode (hard/mixed/soft)
            strategy: Optional strategy for confirming destructive reset
            force: If True, skip confirmation

        Raises:
            ValueError: If ref doesn't exist or invalid mode
            CDEnvironmentError: If uncommitted changes exist (hard mode only)
        """
        self.git_orchestrator.reset(ref, mode, strategy, force)

    @_requires_env_lock
    def create_branch(self, name: str, start_point: str = "HEAD") -> None:
        """Create new branch at start_point.

        Args:
            name: Branch name
            start_point: Commit to branch from (default: HEAD)
        """
        self.git_orchestrator.create_branch(name, start_point)

    @_requires_env_lock
    def delete_branch(self, name: str, force: bool = False) -> None:
        """Delete branch.

        Args:
            name: Branch name
            force: Force delete even if unmerged
        """
        self.git_orchestrator.delete_branch(name, force)

    @_requires_env_lock
    def create_and_switch_branch(self, name: str, start_point: str = "HEAD") -> None:
        """Create new branch and switch to it (git checkout -b semantics).

        This is the atomic equivalent of 'git checkout -b'. It creates a branch
        from start_point and switches to it in one operation, preserving any
        uncommitted workflow changes.

        Args:
            name: Branch name to create
            start_point: Commit to branch from (default: HEAD)

        Raises:
            OSError: If branch already exists or git operations fail
        """
        self.git_orchestrator.create_and_switch_branch(name, start_point)

    @_requires_env_lock
    def switch_branch(self, branch: str, create: bool = False) -> None:
        """Switch to branch and sync environment.

        Args:
            branch: Branch name
            create: Create branch if it doesn't exist

        Raises:
            CDEnvironmentError: If uncommitted workflow changes would be overwritten
        """
        self.git_orchestrator.switch_branch(branch, create)

    def list_branches(self) -> list[tuple[str, bool]]:
        """List all branches with current branch marked.

        Returns:
            List of (branch_name, is_current) tuples
        """
        return self.git_manager.list_branches()

    def get_current_branch(self) -> str | None:
        """Get current branch name.

        Returns:
            Branch name or None if detached HEAD
        """
        return self.git_manager.get_current_branch()

    @_requires_env_lock
    def merge_branch(
        self,
        branch: str,
        message: str | None = None,
        strategy_option: str | None = None,
    ) -> None:
        """Merge branch into current branch and sync environment.

        Args:
            branch: Branch to merge
            message: Custom merge commit message
            strategy_option: Optional strategy option (e.g., "ours" or "theirs" for -X flag)
        """
        self.git_orchestrator.merge_branch(branch, message, strategy_option)

    def validate_merge(
        self,
        branch: str,
        workflow_resolutions: dict,
    ) -> MergeValidation:
        """Validate merge compatibility before execution.

        Checks for node version conflicts that would occur if the merge
        proceeded with the given workflow resolutions.

        Args:
            branch: Branch to merge
            workflow_resolutions: Dict mapping workflow names to "take_base" or "take_target"

        Returns:
            MergeValidation with is_compatible flag and any conflicts
        """
        import tomllib

        from ..merging.merge_validator import MergeValidator
        from ..utils.git import git_show

        # Load configs from both branches
        pyproject_path = Path("pyproject.toml")
        base_content = git_show(self.cec_path, "HEAD", pyproject_path)
        target_content = git_show(self.cec_path, branch, pyproject_path)

        base_config = tomllib.loads(base_content) if base_content else {}
        target_config = tomllib.loads(target_content) if target_content else {}

        validator = MergeValidator()
        return validator.validate(base_config, target_config, workflow_resolutions)

    @_requires_env_lock
    def execute_atomic_merge(
        self,
        branch: str,
        workflow_resolutions: dict,
    ) -> MergeResult:
        """Execute merge with atomic semantics and semantic pyproject merging.

        This method:
        1. Starts git merge without committing
        2. Resolves workflow files per user choices (--ours/--theirs)
        3. Builds merged pyproject.toml using semantic rules
        4. Commits the merge
        5. Syncs environment (nodes, deps, workflows)

        If any step fails, rolls back to pre-merge state.

        Args:
            branch: Branch to merge
            workflow_resolutions: Dict mapping workflow names to "take_base" or "take_target"

        Returns:
            MergeResult with success status and details
        """
        import tomllib

        from ..merging.atomic_executor import AtomicMergeExecutor
        from ..merging.merge_validator import MergeValidator
        from ..models.merge_plan import MergePlan
        from ..utils.git import git_show

        # Load configs to compute final workflow set
        pyproject_path = Path("pyproject.toml")
        base_content = git_show(self.cec_path, "HEAD", pyproject_path)
        target_content = git_show(self.cec_path, branch, pyproject_path)

        base_config = tomllib.loads(base_content) if base_content else {}
        target_config = tomllib.loads(target_content) if target_content else {}

        # Compute final workflow set
        validator = MergeValidator()
        validation = validator.validate(base_config, target_config, workflow_resolutions)

        # Build merge plan
        plan = MergePlan(
            target_branch=branch,
            base_ref="HEAD",
            workflow_resolutions=workflow_resolutions,
            final_workflow_set=validation.merged_workflow_set,
            node_conflicts=validation.conflicts,
            is_compatible=validation.is_compatible,
        )

        # Execute atomic merge
        executor = AtomicMergeExecutor(
            repo_path=self.cec_path,
            pyproject_manager=self.pyproject,
            workspace_path=self.workspace_paths.root,
        )

        result = executor.execute(plan)

        # If merge succeeded, sync environment
        if result.success:
            old_nodes = self.pyproject.nodes.get_existing()
            self.git_orchestrator._sync_environment_after_git(old_nodes)

        return result

    @_requires_env_lock
    def revert_commit(self, commit: str) -> None:
        """Revert a commit by creating new commit that undoes it.

        Args:
            commit: Commit hash to revert
        """
        self.git_orchestrator.revert_commit(commit)

    def get_commit_history(self, limit: int = 10) -> list[dict]:
        """Get commit history for this environment.

        Args:
            limit: Maximum number of commits to return

        Returns:
            List of commit dicts with keys: hash, message, date, date_relative
        """
        return self.git_manager.get_version_history(limit)

    def sync_model_paths(self) -> dict | None:
        """Ensure model symlink is configured for this environment.

        Returns:
            Status dictionary
        """
        logger.debug(f"Configuring model symlink for environment '{self.name}'")
        try:
            self.model_symlink_manager.create_symlink()
            return {
                "status": "linked",
                "target": str(self.global_models_path),
                "link": str(self.models_path)
            }
        except Exception as e:
            logger.error(f"Failed to configure model symlink: {e}")
            raise

    # TODO wrap subprocess completed process instance
    def run(self, args: list[str] | None = None) -> subprocess.CompletedProcess:
        """Run ComfyUI in this environment.

        Args:
            args: Arguments to pass to ComfyUI

        Returns:
            CompletedProcess
        """
        python = self.uv_manager.python_executable
        cmd = [str(python), "main.py"] + (args or [])

        child_env = os.environ.copy()
        child_env["COMFYGIT_ENV_NAME"] = self.name
        child_env["COMFYGIT_CG_RUN_SUPERVISOR"] = "1"

        logger.info(f"Starting ComfyUI with: {' '.join(cmd)}")
        return run_command(
            cmd,
            cwd=self.comfyui_path,
            capture_output=False,
            timeout=None,
            env=child_env,
        )

    # =====================================================
    # Node Management
    # =====================================================

    def list_nodes(self) -> list[NodeInfo]:
        """List all custom nodes in this environment.

        Returns:
            List of NodeInfo objects for all installed custom nodes
        """
        nodes_dict = self.pyproject.nodes.get_existing()
        return list(nodes_dict.values())

    @_requires_env_lock
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
        resolve_with_overlays: bool = False,
    ) -> NodeInfo:
        """Add a custom node to the environment.

        Args:
            identifier: Registry ID or GitHub URL (supports @version)
            is_development: Track as development node
            no_test: Skip dependency resolution testing
            force: Force replacement of existing nodes
            confirmation_strategy: Strategy for confirming replacements
            strict: If True, fail on dependency conflicts instead of auto-resolving
            extras: Optional list of extras to install during sync
            all_extras: Install all optional extras during sync
            resolve_with_overlays: If True, resolve with all active/extra overlays.
                                   If False, node sync defaults to pytorch-only overlays.

        Raises:
            CDNodeNotFoundError: If node not found
            CDNodeConflictError: If node has dependency conflicts
            CDEnvironmentError: If node with same name already exists
        """
        add_kwargs = {}
        if resolve_with_overlays:
            add_kwargs["skip_optional_overlays"] = False

        return self.node_manager.add_node(
            identifier,
            is_development=is_development,
            no_test=no_test,
            force=force,
            confirmation_strategy=confirmation_strategy,
            strict=strict,
            extras=extras,
            all_extras=all_extras,
            **add_kwargs,
        )

    @_requires_env_lock
    def link_development_node(
        self,
        identifier: str,
        source_path: Path | str,
        *,
        name: str | None = None,
        replace_existing: bool = False,
        force: bool = False,
    ) -> NodeDevLinkResult:
        """Convert or add a custom node as a symlinked development checkout."""
        self.git_manager.ensure_gitignore_entry("backups/")
        return self.node_manager.link_development_node(
            identifier,
            source_path,
            name=name,
            replace_existing=replace_existing,
            force=force,
        )

    @_requires_env_lock
    def preview_add_node_dependency_changes(self, identifier: str) -> DependencyResolutionPreview:
        """Preview lockfile dependency changes for adding a node."""
        return self.node_manager.preview_add_node_dependency_changes(identifier)

    @_requires_env_lock
    def apply_reviewed_node_dependency_changes(
        self,
        identifier: str,
        acceptance: DependencyResolutionAcceptance,
    ) -> DependencyResolutionApplyResult:
        """Apply a reviewed node install if the accepted dependency preview is current."""
        return self.node_manager.apply_reviewed_dependency_changes(identifier, acceptance)

    @_requires_env_lock
    def install_nodes_with_progress(
        self,
        node_ids: list[str],
        callbacks: NodeInstallCallbacks | None = None,
        extras: list[str] | None = None,
        all_extras: bool = False,
        resolve_with_overlays: bool = False,
    ) -> tuple[int, list[tuple[str, str]]]:
        """Install multiple nodes with callback support for progress tracking.

        Args:
            node_ids: List of node identifiers to install
            callbacks: Optional callbacks for progress feedback
            extras: Optional list of extras to install during sync
            all_extras: Install all optional extras during sync
            resolve_with_overlays: If True, resolve node installs with all overlays.

        Returns:
            Tuple of (success_count, failed_nodes)
            where failed_nodes is a list of (node_id, error_message) tuples

        Raises:
            CDNodeNotFoundError: If a node is not found
        """
        if callbacks and callbacks.on_batch_start:
            callbacks.on_batch_start(len(node_ids))

        success_count = 0
        failed = []

        for idx, node_id in enumerate(node_ids):
            if callbacks and callbacks.on_node_start:
                callbacks.on_node_start(node_id, idx + 1, len(node_ids))

            try:
                self.add_node(
                    node_id,
                    extras=extras,
                    all_extras=all_extras,
                    resolve_with_overlays=resolve_with_overlays,
                )
                success_count += 1
                if callbacks and callbacks.on_node_complete:
                    callbacks.on_node_complete(node_id, True, None)
            except Exception as e:
                failed.append((node_id, str(e)))
                if callbacks and callbacks.on_node_complete:
                    callbacks.on_node_complete(node_id, False, str(e))

        if callbacks and callbacks.on_batch_complete:
            callbacks.on_batch_complete(success_count, len(node_ids))

        return success_count, failed

    @_requires_env_lock
    def remove_node(self, identifier: str, untrack_only: bool = False) -> NodeRemovalResult:
        """Remove a custom node.

        Args:
            identifier: Node identifier or name
            untrack_only: If True, only remove from pyproject.toml without touching filesystem

        Returns:
            NodeRemovalResult: Details about the removal

        Raises:
            CDNodeNotFoundError: If node not found
        """
        return self.node_manager.remove_node(identifier, untrack_only=untrack_only)

    @_requires_env_lock
    def remove_nodes_with_progress(
        self,
        node_ids: list[str],
        callbacks: NodeInstallCallbacks | None = None
    ) -> tuple[int, list[tuple[str, str]]]:
        """Remove multiple nodes with callback support for progress tracking.

        Args:
            node_ids: List of node identifiers to remove
            callbacks: Optional callbacks for progress feedback

        Returns:
            Tuple of (success_count, failed_nodes)
            where failed_nodes is a list of (node_id, error_message) tuples

        Raises:
            CDNodeNotFoundError: If a node is not found
        """
        if callbacks and callbacks.on_batch_start:
            callbacks.on_batch_start(len(node_ids))

        success_count = 0
        failed = []

        for idx, node_id in enumerate(node_ids):
            if callbacks and callbacks.on_node_start:
                callbacks.on_node_start(node_id, idx + 1, len(node_ids))

            try:
                self.remove_node(node_id)
                success_count += 1
                if callbacks and callbacks.on_node_complete:
                    callbacks.on_node_complete(node_id, True, None)
            except Exception as e:
                failed.append((node_id, str(e)))
                if callbacks and callbacks.on_node_complete:
                    callbacks.on_node_complete(node_id, False, str(e))

        if callbacks and callbacks.on_batch_complete:
            callbacks.on_batch_complete(success_count, len(node_ids))

        return success_count, failed

    @_requires_env_lock
    def update_node(
        self,
        identifier: str,
        confirmation_strategy: ConfirmationStrategy | None = None,
        no_test: bool = False
    ) -> UpdateResult:
        """Update a node based on its source type.

        - Development nodes: Re-scan requirements.txt
        - Registry nodes: Update to latest version
        - Git nodes: Update to latest commit

        Args:
            identifier: Node identifier or name
            confirmation_strategy: Strategy for confirming updates (None = auto-confirm)
            no_test: Skip resolution testing

        Raises:
            CDNodeNotFoundError: If node not found
            CDEnvironmentError: If node cannot be updated
        """
        return self.node_manager.update_node(identifier, confirmation_strategy, no_test)

    def check_development_node_drift(self) -> dict[str, tuple[set[str], set[str]]]:
        """Check if development nodes have requirements drift.

        Returns:
            Dict mapping node_name -> (added_deps, removed_deps)
        """
        return self.node_manager.check_development_node_drift()

    # =====================================================
    # Workflow Management
    # =====================================================

    def list_workflows(self) -> WorkflowSyncStatus:
        """List all workflows categorized by sync status.

        Returns:
            Dict with 'new', 'modified', 'deleted', and 'synced' workflow names
        """
        return self.workflow_manager.get_workflow_sync_status()

    def resolve_workflow(
        self,
        name: str,
        node_strategy: NodeResolutionStrategy | None = None,
        model_strategy: ModelResolutionStrategy | None = None,
        fix: bool = True,
        download_callbacks: BatchDownloadCallbacks | None = None
    ) -> ResolutionResult:
        """Resolve workflow dependencies - orchestrates analysis and resolution.

        Args:
            name: Workflow name to resolve
            node_strategy: Strategy for resolving missing nodes
            model_strategy: Strategy for resolving ambiguous/missing models
            fix: Attempt to fix unresolved issues with strategies
            download_callbacks: Optional callbacks for batch download progress (CLI provides)

        Returns:
            ResolutionResult with changes made

        Raises:
            FileNotFoundError: If workflow not found
        """
        # Analyze and resolve workflow (both cached for performance)
        _, result = self.workflow_manager.analyze_and_resolve_workflow(name)

        # Apply auto-resolutions (reconcile with pyproject.toml)
        self.workflow_manager.apply_resolution(result)

        # Check if there are any unresolved issues
        if result.has_issues and fix:
            # Fix issues with strategies (progressive writes: models AND nodes saved immediately)
            result = self.workflow_manager.fix_resolution(
                result,
                node_strategy,
                model_strategy
            )

        # Execute pending downloads if any download intents exist
        if result.has_download_intents:
            result.download_results = self.workflow_manager.execute_pending_downloads(result, download_callbacks)

            # After successful downloads, update workflow JSON with resolved paths
            # Re-resolve to get fresh model data (cached, so minimal cost)
            if result.download_results and any(dr.success for dr in result.download_results):
                _, fresh_result = self.workflow_manager.analyze_and_resolve_workflow(name)
                self.workflow_manager.update_workflow_model_paths(fresh_result)

        return result

    def get_uninstalled_nodes(self, workflow_name: str | None = None) -> list[str]:
        """Get list of node package IDs referenced in workflows but not installed.

        Compares nodes referenced in workflow sections against installed nodes
        to identify which nodes need installation.

        Returns:
            List of node package IDs that are referenced in workflows but not installed.
            Empty list if all workflow nodes are already installed.

        Example:
            >>> env.resolve_workflow("my_workflow")
            >>> missing = env.get_uninstalled_nodes()
            >>> # ['rgthree-comfy', 'comfyui-depthanythingv2', ...]
        """
        # Get all node IDs referenced in workflows
        workflow_node_ids = set()
        if workflow_name:
            if workflow := self.pyproject.workflows.get_workflow(workflow_name):
                workflows = {workflow_name: workflow}
            else:
                logger.warning(f"Workflow '{workflow_name}' not found")
                return []
        else:
            workflows = self.pyproject.workflows.get_all_with_resolutions()

        for workflow_data in workflows.values():
            node_list = workflow_data.get('nodes', [])
            workflow_node_ids.update(node_list)

        logger.debug(f"Workflow node references: {workflow_node_ids}")

        # Get installed node IDs
        installed_nodes = self.pyproject.nodes.get_existing()
        installed_node_ids = set(installed_nodes.keys())
        logger.debug(f"Installed nodes: {installed_node_ids}")

        # Find nodes referenced in workflows but not installed. Existing
        # manifests may contain exact installed aliases such as custom_nodes
        # directory names, so resolve those before reporting missing packages.
        uninstalled_ids = [
            node_id
            for node_id in workflow_node_ids
            if not resolve_installed_node_alias(node_id, installed_nodes)
        ]
        logger.debug(f"Uninstalled nodes: {uninstalled_ids}")

        return uninstalled_ids

    def get_unused_nodes(self, exclude: list[str] | None = None) -> list[NodeInfo]:
        """Get installed nodes not referenced by any workflow.

        Uses the same auto-resolution flow as status command to ensure we capture
        all nodes actually needed by workflows, including those from custom_node_map.

        Args:
            exclude: Optional list of package IDs to exclude from pruning

        Returns:
            List of NodeInfo for unused nodes that can be safely removed

        Example:
            >>> unused = env.get_unused_nodes()
            >>> # [NodeInfo(registry_id='old-node'), ...]
            >>> # Or with exclusions:
            >>> unused = env.get_unused_nodes(exclude=['keep-this-node'])
        """
        # Get workflow status (triggers auto-resolution with caching)
        workflow_status = self.workflow_manager.get_workflow_status()

        # Aggregate packages from all workflows
        all_needed_packages = set()
        for workflow_analysis in workflow_status.analyzed_workflows:
            for resolved_node in workflow_analysis.resolution.nodes_resolved:
                # Only count non-optional nodes with actual package IDs
                if resolved_node.package_id and not resolved_node.is_optional:
                    all_needed_packages.add(resolved_node.package_id)

        logger.debug(f"Packages needed by workflows: {all_needed_packages}")

        # Get installed nodes
        installed_nodes = self.pyproject.nodes.get_existing()
        installed_node_ids = set(installed_nodes.keys())
        logger.debug(f"Installed nodes: {installed_node_ids}")

        # Calculate unused = installed - needed
        unused_ids = installed_node_ids - all_needed_packages

        # Apply exclusions
        if exclude:
            unused_ids -= set(exclude)
            logger.debug(f"After exclusions: {unused_ids}")

        return [installed_nodes[nid] for nid in unused_ids]

    @_requires_env_lock
    def update_node_criticality(self, node_identifier: str, criticality: str) -> bool:
        """Update package-level custom-node criticality.

        Custom-node criticality is a user-declared deployment/readiness signal.
        It is not inferred from workflow graph usage because custom nodes may
        affect runtime behavior through hooks, extensions, or side effects.
        """
        return self.pyproject.nodes.set_criticality(node_identifier, criticality)

    @_requires_env_lock
    def prune_unused_nodes(
        self,
        exclude: list[str] | None = None,
        callbacks: NodeInstallCallbacks | None = None
    ) -> tuple[int, list[tuple[str, str]]]:
        """Remove unused nodes from environment.

        Args:
            exclude: Package IDs to keep even if unused
            callbacks: Progress callbacks

        Returns:
            Tuple of (success_count, failed_removals)
        """
        unused = self.get_unused_nodes(exclude=exclude)

        if not unused:
            return (0, [])

        # Use existing batch removal
        node_ids = [node.registry_id or node.name for node in unused]
        return self.remove_nodes_with_progress(node_ids, callbacks)

    def has_committable_changes(self) -> bool:
        """Check if there are any committable changes (workflows OR git).

        This is the clean API for determining if a commit is possible.
        Checks both workflow file sync status AND git uncommitted changes.

        Returns:
            True if there are committable changes, False otherwise
        """
        # Check workflow file changes (new/modified/deleted workflows)
        workflow_status = self.workflow_manager.get_workflow_status()
        has_workflow_changes = workflow_status.sync_status.has_changes

        # Check git uncommitted changes (pyproject.toml, uv.lock, etc.)
        has_git_changes = self.git_manager.has_uncommitted_changes()

        return has_workflow_changes or has_git_changes

    @_requires_env_lock
    def commit(self, message: str | None = None) -> None:
        """Commit changes to git repository.

        Args:
            message: Optional commit message

        Raises:
            OSError: If git commands fail
        """
        return self.git_manager.commit_all(message)

    @_requires_env_lock
    def execute_commit(
        self,
        workflow_status: DetailedWorkflowStatus | None = None,
        message: str | None = None,
        allow_issues: bool = False,
    ) -> None:
        """Execute commit using cached or provided analysis.

        Args:
            message: Optional commit message
            allow_issues: Allow committing even with unresolved issues
        """
        # Use provided analysis or prepare a new one
        if not workflow_status:
            workflow_status = self.workflow_manager.get_workflow_status()

        # Check if changes are safe to commit (no unresolved issues)
        if not workflow_status.is_commit_safe and not allow_issues:
            logger.error("Cannot commit with unresolved issues. Use --allow-issues to force.")
            return

        # Commit can be responsible for cleanup even when the only pending
        # change is a stale tracked workflow_api artifact.
        cleanup_config = self.pyproject.load()
        cleanup_result = self.workflow_manager.cleanup_orphaned_workflow_state(
            config=cleanup_config,
        )
        if cleanup_result["workflow_entries"] > 0:
            # Clean up orphaned models after workflow sections are removed.
            self.pyproject.models.cleanup_orphans(config=cleanup_config)
            self.pyproject.save(cleanup_config)

        # Check if there are any changes to commit (workflows OR git)
        has_workflow_changes = workflow_status.sync_status.has_changes
        has_git_changes = self.git_manager.has_uncommitted_changes()

        if not has_workflow_changes and not has_git_changes:
            logger.error("No changes to commit")
            return

        # Apply auto-resolutions to pyproject.toml for workflows with changes
        # BATCHED MODE: Load config once, pass through all operations, save once
        logger.info("Committing all changes...")
        config = self.pyproject.load()

        for wf_analysis in workflow_status.analyzed_workflows:
            if wf_analysis.sync_state in ("new", "modified"):
                # Apply resolution results to pyproject (in-memory mutations)
                self.workflow_manager.apply_resolution(wf_analysis.resolution, config=config)

        # Clean up orphaned workflow entries and workflow API prompt artifacts.
        # This handles BOTH:
        # 1. Committed workflows deleted from ComfyUI (detected by sync_status.deleted)
        # 2. Resolved-but-never-committed workflows deleted from ComfyUI (only in pyproject)
        cleanup_result = self.workflow_manager.cleanup_orphaned_workflow_state(config=config)
        if cleanup_result["workflow_entries"] > 0:
            logger.debug(f"Removed {cleanup_result['workflow_entries']} workflow section(s)")

            # Clean up orphaned models (must run AFTER workflow sections are removed).
            self.pyproject.models.cleanup_orphans(config=config)

        # Save all changes at once
        self.pyproject.save(config)

        logger.info("Copying workflows from ComfyUI to .cec...")
        copy_results = self.workflow_manager.copy_all_workflows()
        copied_count = len([r for r in copy_results.values() if r and r != "deleted"])
        logger.debug(f"Copied {copied_count} workflow(s)")

        self.commit(message)

    # =====================================================
    # Workflow Contract Management
    # =====================================================

    @_requires_env_lock
    def get_manifest_snapshot(self) -> EnvironmentManifestSnapshot:
        """Return a typed read-only projection of the current manifest."""
        return self.pyproject.get_manifest_snapshot()

    @_requires_env_lock
    def get_workflow_execution_contract(self, workflow_name: str) -> WorkflowExecutionContract | None:
        """Get the saved execution contract for a workflow."""
        return self.pyproject.workflows.get_execution_contract(workflow_name)

    @_requires_env_lock
    def set_workflow_execution_contract(
        self,
        workflow_name: str,
        contract: WorkflowExecutionContract,
        api_prompt_data: dict | None = None,
    ) -> None:
        """Create or replace the saved execution contract for a workflow."""
        if api_prompt_data is not None:
            rel_path = _workflow_api_prompt_relpath(workflow_name)
            api_prompt_path = self.cec_path / rel_path
            api_prompt_path.parent.mkdir(parents=True, exist_ok=True)
            with api_prompt_path.open("w", encoding="utf-8") as handle:
                json.dump(api_prompt_data, handle, indent=2)
                handle.write("\n")

            contract.api_prompt_file = rel_path.as_posix()
            contract.api_prompt_source = "comfyui_frontend"
            contract.api_prompt_generated_by = "comfygit-manager"
            contract.api_prompt_generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.pyproject.workflows.set_execution_contract(workflow_name, contract)

    @_requires_env_lock
    def remove_workflow_execution_contract(self, workflow_name: str) -> bool:
        """Remove the saved execution contract for a workflow."""
        contract = self.pyproject.workflows.get_execution_contract(workflow_name)
        removed = self.pyproject.workflows.remove_execution_contract(workflow_name)
        if removed and contract is not None and contract.api_prompt_file:
            api_prompt_path = self.cec_path / contract.api_prompt_file
            try:
                if api_prompt_path.exists() and api_prompt_path.is_file():
                    api_prompt_path.unlink()
            except OSError as exc:
                logger.warning(
                    "Failed to remove API prompt artifact for workflow '%s': %s",
                    workflow_name,
                    exc,
                )
        return removed

    # =====================================================
    # Model Source Management
    # =====================================================

    @_requires_env_lock
    def add_model_source(self, identifier: str, url: str) -> ModelSourceResult:
        """Add a download source URL to a model.

        Args:
            identifier: Model hash or filename
            url: Download URL for the model

        Returns:
            ModelSourceResult with success status and model details
        """
        return self.model_manager.add_model_source(identifier, url)

    @_requires_env_lock
    def remove_model_source(self, identifier: str, url: str) -> ModelSourceResult:
        """Remove a download source URL from a model.

        Args:
            identifier: Model hash or filename
            url: Download URL to remove

        Returns:
            ModelSourceResult with success status and model details
        """
        return self.model_manager.remove_model_source(identifier, url)

    def get_models_without_sources(self) -> list[ModelSourceStatus]:
        """Get all models in pyproject that don't have download sources.

        Returns:
            List of ModelSourceStatus objects with model and local availability
        """
        return self.model_manager.get_models_without_sources()

    # =====================================================
    # Constraint Management
    # =====================================================

    def add_constraint(self, package: str) -> None:
        """Add a constraint dependency."""
        self.pyproject.uv_config.add_constraint(package)

    def remove_constraint(self, package: str) -> bool:
        """Remove a constraint dependency."""
        return self.pyproject.uv_config.remove_constraint(package)

    def list_constraints(self) -> list[str]:
        """List constraint dependencies."""
        return self.pyproject.uv_config.get_constraints()

    # ===== Python Dependency Management =====

    def add_dependencies(
        self,
        packages: list[str] | None = None,
        requirements_file: Path | None = None,
        upgrade: bool = False,
        group: str | None = None,
        dev: bool = False,
        optional: str | None = None,
        editable: bool = False,
        bounds: str | None = None,
        no_build_isolation: bool = False
    ) -> dict:
        """Add Python dependencies to the environment.

        Uses uv add to add packages to [project.dependencies] and install them.
        Applies package substitutions from package_config.toml (e.g., opencv-python
        is automatically replaced with opencv-contrib-python-headless).

        Args:
            packages: List of package specifications (e.g., ['requests>=2.0.0', 'pillow'])
            requirements_file: Path to requirements.txt file to add packages from
            upgrade: Whether to upgrade existing packages
            group: Dependency group name (e.g., 'optional-cuda')
            dev: Add to dev dependencies
            optional: Optional dependency extra name (project.optional-dependencies)
            editable: Install as editable (for local development)
            bounds: Version specifier style ('lower', 'major', 'minor', 'exact')
            no_build_isolation: Disable build isolation for specified packages

        Returns:
            Dict with:
                - output: UV command output
                - substitutions: Dict of {original: substituted} for any packages that were replaced

        Raises:
            UVCommandError: If uv add fails
            ValueError: If neither packages nor requirements_file is provided
        """
        if not packages and not requirements_file:
            raise ValueError("Either packages or requirements_file must be provided")

        substitutions: dict[str, str] = {}
        final_packages: list[str] | None = None

        # If requirements file provided, read and parse it
        if requirements_file:
            final_packages = self._read_requirements_file(requirements_file)
        elif packages:
            final_packages = list(packages)

        # Apply package substitutions
        if final_packages:
            transformed_packages = []
            for pkg in final_packages:
                substituted = self.package_config.apply_substitution(pkg)
                if substituted != pkg:
                    substitutions[pkg] = substituted
                    logger.info(f"Package substitution: {pkg} → {substituted}")
                transformed_packages.append(substituted)
            final_packages = transformed_packages

        output = self.uv_manager.add_dependency(
            packages=final_packages,
            requirements_file=None,  # We've already parsed it
            upgrade=upgrade,
            group=group,
            dev=dev,
            optional=optional,
            editable=editable,
            bounds=bounds,
            no_build_isolation=no_build_isolation
        )

        return {"output": output, "substitutions": substitutions}

    def _read_requirements_file(self, requirements_file: Path) -> list[str]:
        """Read and parse a requirements.txt file.

        Strips comments and handles basic formatting.

        Args:
            requirements_file: Path to requirements.txt

        Returns:
            List of requirement strings
        """
        requirements = []
        with open(requirements_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Skip -r includes (recursive requirements)
                if line.startswith('-r '):
                    continue
                # Skip other pip flags
                if line.startswith('-'):
                    continue
                # Strip inline comments
                if '#' in line:
                    line = line.split('#', 1)[0].strip()
                if line:
                    requirements.append(line)
        return requirements

    def remove_dependencies(self, packages: list[str]) -> dict:
        """Remove Python dependencies from the environment.

        Uses uv remove to remove packages from [project.dependencies] and uninstall them.
        Safely handles packages that don't exist in dependencies.

        Args:
            packages: List of package names to remove

        Returns:
            Dict with 'removed' (list of packages removed) and 'skipped' (list of packages not in deps)

        Raises:
            UVCommandError: If uv remove fails for existing packages
        """
        return self.uv_manager.remove_dependency(packages=packages)

    def list_dependencies(self, all: bool = False) -> dict[str, list[str]]:
        """List project dependencies.

        Args:
            all: If True, include all dependency groups. If False, only base dependencies.

        Returns:
            Dictionary mapping group name to list of dependencies.
            Base dependencies are always under "dependencies" key and appear first.
        """
        config = self.pyproject.load()
        base_deps = config.get('project', {}).get('dependencies', [])

        result = {"dependencies": base_deps}

        if all:
            dep_groups = self.pyproject.dependencies.get_groups()
            result.update(dep_groups)

        return result

    # =====================================================
    # Export/Import
    # =====================================================

    def export_environment(
        self,
        output_path: Path,
        callbacks: ExportCallbacks | None = None,
        allow_issues: bool = False
    ) -> Path:
        """Export environment as .tar.gz bundle.

        Args:
            output_path: Path for output tarball
            callbacks: Optional callbacks for warnings/progress
            allow_issues: Allow export even with unresolved workflow issues

        Returns:
            Path to created tarball

        Raises:
            CDExportError: If environment has uncommitted changes or unresolved issues (unless allow_issues)
        """
        from ..managers.export_import_manager import ExportImportManager
        from ..models.exceptions import CDExportError, ExportErrorContext
        from ..models.shared import ModelWithoutSourceInfo
        from ..services.environment_readiness import build_environment_readiness

        readiness = build_environment_readiness(self, include_blocking=True)

        for issue in readiness.blocking_issues:
            if issue.type == "uncommitted_workflows":
                context = ExportErrorContext(uncommitted_workflows=issue.details)
                raise CDExportError(issue.message, context=context)

            if issue.type == "uncommitted_git_changes":
                context = ExportErrorContext(uncommitted_git_changes=True)
                raise CDExportError(issue.message, context=context)

            if issue.type == "unresolved_issues" and not allow_issues:
                context = ExportErrorContext(has_unresolved_issues=True)
                raise CDExportError(issue.message, context=context)

        if callbacks and readiness.warnings.models_without_sources:
            callbacks.on_models_without_sources([
                ModelWithoutSourceInfo(
                    filename=warning.filename,
                    hash=warning.hash or "",
                    workflows=list(warning.workflows),
                )
                for warning in readiness.warnings.models_without_sources
            ])

        # Auto-populate git info for dev nodes before export
        self._auto_populate_dev_node_git_info(callbacks)

        # Create export
        manager = ExportImportManager(self.cec_path, self.comfyui_path)
        return manager.create_export(output_path, self.pyproject)

    def _auto_populate_dev_node_git_info(
        self,
        callbacks: ExportCallbacks | None = None
    ) -> None:
        """Auto-populate git info (repository/branch/pinned_commit) for dev nodes.

        Called during export to capture git state for dev nodes that have git remotes.
        This enables teammates to clone from the same repository.

        Dev nodes without git remotes will trigger a callback notification but
        will still be exported (they just can't be shared).
        """
        from ..analyzers.node_git_analyzer import get_node_git_info

        nodes = self.pyproject.nodes.get_existing()
        config = self.pyproject.load()
        modified = False

        for identifier, node_info in nodes.items():
            if node_info.source != 'development':
                continue

            node_path = self.custom_nodes_path / node_info.name
            if not node_path.exists():
                continue

            # Get git info from the node's directory
            git_info = get_node_git_info(node_path)

            if git_info is None:
                # Not a git repo - notify callback
                no_git_callback = getattr(callbacks, 'on_dev_node_no_git', None)
                if callable(no_git_callback):
                    no_git_callback(node_info.name)
                continue

            if not git_info.remote_url:
                # Git repo but no remote - notify callback
                no_git_callback = getattr(callbacks, 'on_dev_node_no_git', None)
                if callable(no_git_callback):
                    no_git_callback(node_info.name)
                continue

            # Update node info with git data
            node_data = config['tool']['comfygit']['nodes'].get(identifier, {})
            update_needed = False

            if git_info.remote_url and node_data.get('repository') != git_info.remote_url:
                node_data['repository'] = git_info.remote_url
                update_needed = True

            if git_info.branch and node_data.get('branch') != git_info.branch:
                node_data['branch'] = git_info.branch
                update_needed = True

            if git_info.commit and node_data.get('pinned_commit') != git_info.commit:
                node_data['pinned_commit'] = git_info.commit
                update_needed = True

            if update_needed:
                config['tool']['comfygit']['nodes'][identifier] = node_data
                modified = True
                logger.info(f"Captured git info for dev node '{node_info.name}'")

        if modified:
            self.pyproject.save(config)

    def finalize_import(
        self,
        model_strategy: str = "all",
        callbacks: ImportCallbacks | None = None,
        no_manager: bool = False,
        *,
        create_import_commit: bool = True,
        fail_on_sync_errors: bool = False,
    ) -> None:
        """Complete import setup after .cec extraction.

        Assumes .cec directory is already populated (from tarball or git).

        Phases:
            1. Clone/restore ComfyUI from cache and configure PyTorch
            2. Initialize git repository
            3. Copy workflows to ComfyUI user directory
            4. Sync dependencies, custom nodes, and workflows (via sync())
            5. Prepare and resolve models based on strategy

        Args:
            model_strategy: "all", "required", or "skip"
            callbacks: Optional progress callbacks
            no_manager: Skip comfygit-manager install/registration (headless mode)
            create_import_commit: Commit final import/materialization changes
            fail_on_sync_errors: Raise if sync reports or raises dependency errors

        Raises:
            ValueError: If ComfyUI already exists or .cec not properly initialized
        """
        from ..caching.comfyui_cache import ComfyUICacheManager, ComfyUISpec
        from ..utils.comfyui_ops import clone_comfyui
        from ..utils.git import git_rev_parse

        logger.info(f"Finalizing import for environment: {self.name}")

        # Verify environment state
        if self.comfyui_path.exists():
            raise ValueError("Environment already has ComfyUI - cannot finalize import")

        # Strip local filesystem path sources (editable dev installs from export machine)
        self._strip_local_path_sources()

        # Ensure overlay migration runs before finalize-import sync.
        # This guarantees .local-uv-config -> overlays/.local.toml happens prior to sync().
        _ = self.overlay_manager

        # Phase 1: Clone or restore ComfyUI from cache
        comfyui_cache = ComfyUICacheManager(cache_base_path=self.workspace_paths.cache)

        # Read ComfyUI version from pyproject.toml
        comfyui_version = None
        comfyui_version_type = None
        try:
            pyproject_data = self.pyproject.load()
            comfygit_config = pyproject_data.get("tool", {}).get("comfygit", {})
            comfyui_version = comfygit_config.get("comfyui_version")
            comfyui_version_type = comfygit_config.get("comfyui_version_type")
        except Exception as e:
            logger.warning(f"Could not read comfyui_version from pyproject.toml: {e}")

        if comfyui_version:
            version_desc = f"{comfyui_version_type} {comfyui_version}" if comfyui_version_type else comfyui_version
            logger.debug(f"Using comfyui_version from pyproject: {version_desc}")

        # Auto-detect version type if not specified
        if not comfyui_version_type and comfyui_version:
            if comfyui_version.startswith('v'):
                comfyui_version_type = "release"
            elif comfyui_version in ("main", "master"):
                comfyui_version_type = "branch"
            else:
                comfyui_version_type = "commit"
            logger.debug(f"Auto-detected version type: {comfyui_version_type}")

        # Create version spec
        spec = ComfyUISpec(
            version=comfyui_version or "main",
            version_type=comfyui_version_type or "branch",
            commit_sha=None
        )

        # Check cache first
        cached_path = comfyui_cache.get_cached_comfyui(spec)

        if cached_path:
            if callbacks:
                callbacks.on_phase("restore_comfyui", f"Restoring ComfyUI {spec.version} from cache...")
            logger.info(f"Restoring ComfyUI {spec.version} from cache")
            shutil.copytree(cached_path, self.comfyui_path)
        else:
            if callbacks:
                callbacks.on_phase("clone_comfyui", f"Cloning ComfyUI {spec.version}...")
            logger.info(f"Cloning ComfyUI {spec.version}")
            clone_comfyui(self.comfyui_path, comfyui_version)

            # Cache the fresh clone
            commit_sha = git_rev_parse(self.comfyui_path, "HEAD")
            if commit_sha:
                spec.commit_sha = commit_sha
                comfyui_cache.cache_comfyui(spec, self.comfyui_path)
                logger.info(f"Cached ComfyUI {spec.version} ({commit_sha[:7]})")
            else:
                logger.warning(f"Could not determine commit SHA for ComfyUI {spec.version}")

        # Extract builtin nodes for imported environment
        from ..utils.builtin_extractor import extract_comfyui_builtins

        try:
            if callbacks:
                callbacks.on_phase("extract_builtins", "Extracting builtin nodes...")

            builtins_path = self.cec_path / "comfyui_builtins.json"

            # Check if already exists (from exported bundle)
            if builtins_path.exists():
                logger.debug("Builtin config already exists from export, skipping extraction")
            else:
                extract_comfyui_builtins(self.comfyui_path, builtins_path)
                logger.info(f"Extracted builtin nodes to {builtins_path.name}")
        except Exception as e:
            logger.warning(f"Failed to extract builtin nodes: {e}")
            logger.warning("Workflow resolution will fall back to global static config")

        # Extract folder paths from ComfyUI installation
        from ..utils.folder_paths_extractor import extract_folder_paths

        try:
            folder_paths_json = self.cec_path / "comfyui_folder_paths.json"
            extract_folder_paths(self.comfyui_path, folder_paths_json)
            logger.info(f"Extracted folder paths to {folder_paths_json.name}")
        except Exception as e:
            logger.warning(f"Failed to extract folder paths: {e}")
            logger.warning("Model category validation will fall back to static config")

        # Extract model loader widget metadata from ComfyUI installation
        from ..utils.model_loader_extractor import extract_comfyui_model_loaders

        try:
            model_loaders_json = self.cec_path / "comfyui_model_loaders.json"
            extract_comfyui_model_loaders(self.comfyui_path, model_loaders_json)
            logger.info(f"Extracted model loaders to {model_loaders_json.name}")
        except Exception as e:
            logger.warning(f"Failed to extract model loader metadata: {e}")
            logger.warning("Model loader detection will fall back to static config")

        # Remove ComfyUI's default models directory (will be replaced with symlink)
        models_dir = self.comfyui_path / "models"
        if models_dir.exists() and not models_dir.is_symlink():
            rmtree(models_dir)

        # Remove ComfyUI's default input/output directories (will be replaced with symlinks)
        from ..utils.symlink_utils import is_link

        input_dir = self.comfyui_path / "input"
        if input_dir.exists() and not is_link(input_dir):
            rmtree(input_dir)
            logger.debug("Removed ComfyUI's default input directory during import")

        output_dir = self.comfyui_path / "output"
        if output_dir.exists() and not is_link(output_dir):
            rmtree(output_dir)
            logger.debug("Removed ComfyUI's default output directory during import")

        # Create symlinks for user content and system nodes
        self.user_content_manager.create_directories()
        self.user_content_manager.create_symlinks()

        # Create default ComfyUI user settings (skip templates panel on first launch)
        user_settings_dir = self.comfyui_path / "user" / "default"
        user_settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = user_settings_dir / "comfy.settings.json"
        if not settings_file.exists():
            settings_file.write_text('{"Comfy.TutorialCompleted": true}')
            logger.debug("Created default user settings (skip templates panel)")

        # Auto-register comfygit-manager if present in imported environment
        # (replaces legacy symlink system - manager is now per-environment)
        if no_manager:
            self._prepare_headless_import()
            logger.info("Manager registration skipped during import (--no-manager)")
        else:
            self._register_imported_manager()

        # Phase 1.5: Probe PyTorch and configure backend
        # Read Python version from .python-version file
        python_version_file = self.cec_path / ".python-version"
        python_version = python_version_file.read_text(encoding='utf-8').strip() if python_version_file.exists() else "3.12"

        if self.torch_backend:
            from ..managers.pytorch_backend_manager import PyTorchBackendManager

            if callbacks:
                callbacks.on_phase("probe_pytorch", "Detecting PyTorch backend...")

            # Migrate schema v1 environments (strips embedded PyTorch config)
            migrated = self.pyproject.migrate_pytorch_config()
            if migrated:
                logger.info("Migrated imported environment to schema v2")

            # Use dry-run probe to detect backend
            pytorch_manager = PyTorchBackendManager(self.cec_path)
            resolved_backend = pytorch_manager.probe_and_set_backend(python_version, self.torch_backend)

            if self.torch_backend == "auto":
                logger.info(f"PyTorch backend: auto-detected as {resolved_backend}")
            else:
                logger.info(f"PyTorch backend: {resolved_backend}")

        # Phase 2: Setup git repository
        # For git imports: .git already exists with remote, just ensure gitignore
        # For tarball imports: .git doesn't exist, initialize fresh repo
        git_existed = (self.cec_path / ".git").exists()

        if callbacks:
            phase_msg = "Ensuring git configuration..." if git_existed else "Initializing git repository..."
            callbacks.on_phase("init_git", phase_msg)

        if git_existed:
            # Git import case: preserve existing repo, just ensure gitignore
            logger.info("Git repository already exists (imported from git), preserving remote and history")
            self.git_manager._create_gitignore()
            self.git_manager.ensure_git_identity()
        else:
            # Tarball import case: initialize fresh repo
            logger.info("Initializing new git repository")
            self.git_manager.initialize_environment_repo("Imported environment")

        # Phase 3: Copy workflows
        if callbacks:
            callbacks.on_phase("copy_workflows", "Setting up workflows...")

        workflows_src = self.cec_path / "workflows"
        workflows_dst = self.comfyui_path / "user" / "default" / "workflows"
        workflows_dst.mkdir(parents=True, exist_ok=True)

        if workflows_src.exists():
            for workflow_file in workflows_src.glob("*.json"):
                shutil.copy2(workflow_file, workflows_dst / workflow_file.name)
                if callbacks:
                    callbacks.on_workflow_copied(workflow_file.name)

        shared_overlays = [
            info.name
            for info in self.overlay_manager.list_overlays()
            if not info.is_local
        ]
        if shared_overlays:
            overlay_msg = (
                f"Detected {len(shared_overlays)} shared overlay(s): "
                f"{', '.join(shared_overlays)}"
            )
            logger.info(overlay_msg)
            if callbacks:
                callbacks.on_phase("detect_overlays", overlay_msg)

        # Phase 3.5: Ensure ComfyUI base requirements are present
        # Web-exported environments may have dependencies=[] since the exact
        # requirements.txt isn't known at export time. Add them now from the
        # freshly cloned ComfyUI so uv sync installs everything.
        comfyui_reqs = self.comfyui_path / "requirements.txt"
        if comfyui_reqs.exists():
            pyproject_data = self.pyproject.load()
            current_deps = pyproject_data.get("project", {}).get("dependencies", [])
            if not current_deps:
                logger.info("Adding ComfyUI requirements (empty dependencies detected)...")
                if callbacks:
                    callbacks.on_phase("add_requirements", "Adding ComfyUI base requirements...")
                self.uv_manager.add_requirements_with_sources(comfyui_reqs, frozen=True)

        # Phase 4: Sync dependencies, custom nodes, and workflows
        # This single sync() call handles all dependency installation, node syncing, and workflow restoration
        if callbacks:
            callbacks.on_phase("sync_environment", "Syncing dependencies and custom nodes...")

        try:
            # During import, don't remove ComfyUI builtins (fresh clone has example files)
            # Enable verbose to show real-time uv output during dependency installation
            sync_result = self.sync(remove_extra_nodes=False, sync_callbacks=callbacks, verbose=True)
            if sync_result.success and sync_result.nodes_installed and callbacks:
                for node_name in sync_result.nodes_installed:
                    callbacks.on_node_installed(node_name)
            elif not sync_result.success and callbacks:
                for error in sync_result.errors:
                    callbacks.on_error(f"Node sync: {error}")
            if fail_on_sync_errors and not sync_result.success:
                error_text = "; ".join(sync_result.errors) if sync_result.errors else "unknown sync error"
                raise RuntimeError(f"Environment sync failed during materialization: {error_text}")
        except Exception as e:
            if callbacks:
                callbacks.on_error(f"Node sync failed: {e}")
            if fail_on_sync_errors:
                raise

        # Phase 5: Prepare and resolve models
        if callbacks:
            callbacks.on_phase("resolve_models", f"Resolving workflows ({model_strategy} strategy)...")

        # Always prepare models to copy sources from global table, even for "skip"
        # This ensures download intents are preserved for later resolution
        workflows_with_intents = self.model_manager.prepare_import_with_model_strategy(model_strategy)

        # Only auto-resolve if not "skip" strategy
        workflows_to_resolve = [] if model_strategy == "skip" else workflows_with_intents

        # prepare_import_with_model_strategy() may update pyproject model entries.
        # Invalidate per-workflow cache entries so resolve_workflow() sees fresh
        # download intents instead of stale session-cached resolutions.
        for workflow_name in workflows_to_resolve:
            self.workflow_cache.invalidate(self.name, workflow_name)

        # Resolve workflows with download intents
        from ..models.workflow import BatchDownloadCallbacks
        from ..strategies.auto import AutoModelStrategy, AutoNodeStrategy

        download_failures = []

        # Create download callbacks adapter if import callbacks provided
        download_callbacks = None
        if callbacks:
            download_callbacks = BatchDownloadCallbacks(
                on_batch_start=callbacks.on_download_batch_start,
                on_file_start=callbacks.on_download_file_start,
                on_file_progress=callbacks.on_download_file_progress,
                on_file_complete=callbacks.on_download_file_complete,
                on_batch_complete=callbacks.on_download_batch_complete
            )

        for workflow_name in workflows_to_resolve:
            try:
                result = self.resolve_workflow(
                    name=workflow_name,
                    model_strategy=AutoModelStrategy(),
                    node_strategy=AutoNodeStrategy(),
                    download_callbacks=download_callbacks
                )

                # Track successful vs failed downloads from actual download results
                successful_downloads = sum(1 for dr in result.download_results if dr.success)
                failed_downloads = [
                    (workflow_name, dr.filename)
                    for dr in result.download_results
                    if not dr.success
                ]

                download_failures.extend(failed_downloads)

                if callbacks:
                    callbacks.on_workflow_resolved(workflow_name, successful_downloads)

            except Exception as e:
                if callbacks:
                    callbacks.on_error(f"Failed to resolve {workflow_name}: {e}")

        # Report download failures
        if download_failures and callbacks:
            callbacks.on_download_failures(download_failures)

        if no_manager:
            self._set_headless_marker()

        # Mark environment as fully initialized
        from ..utils.environment_cleanup import mark_environment_complete
        mark_environment_complete(self.cec_path)

        # Phase 7: Commit all changes from import process
        # This captures: workflows copied, nodes synced, models resolved, pyproject updates
        if create_import_commit and self.git_manager.has_uncommitted_changes():
            self.git_manager.commit_with_identity("Imported environment", add_all=True)
            logger.info("Committed import changes")

        if download_failures and model_strategy != "skip":
            from ..models.exceptions import CDModelDownloadError

            formatted_failures = ", ".join(
                f"{model_name} (from {workflow_name})"
                for workflow_name, model_name in download_failures
            )
            raise CDModelDownloadError(
                f"{len(download_failures)} model(s) failed to download: {formatted_failures}",
                failures=download_failures
            )

        logger.info("Import finalization completed successfully")

    def _strip_local_path_sources(self) -> None:
        """Remove uv sources with local filesystem paths (editable dev installs).

        When environments are exported from dev machines, they may contain
        [tool.uv.sources.package-name] entries with local paths like:
            path = "/home/dev/projects/my-package"
            editable = true

        These paths don't exist on other machines and cause sync failures.
        This method removes any source entries that use local paths.
        """
        removed = self.pyproject.strip_local_path_sources()
        for pkg_name in removed:
            logger.info(f"Stripped local path source: {pkg_name}")

    def _untrack_uvlock_if_tracked(self) -> None:
        """Untrack uv.lock if it was previously tracked in git.

        uv.lock is now gitignored (platform-specific PyTorch variants).
        For existing environments where it was tracked, untrack it.
        """
        from ..utils.git import _git

        # Check if uv.lock is tracked
        result = _git(
            ["ls-files", "uv.lock"],
            self.cec_path,
            check=False
        )
        if result.stdout.strip() == "uv.lock":
            # Untrack without deleting the file
            _git(["rm", "--cached", "uv.lock"], self.cec_path, check=False)
            logger.info("Untracked uv.lock (now gitignored)")

    def _untrack_generated_metadata_if_tracked(self) -> None:
        """Untrack generated ComfyUI metadata files if previously committed."""
        from ..utils.git import _git

        for filename in (
            "comfyui_builtins.json",
            "comfyui_folder_paths.json",
            "comfyui_model_loaders.json",
        ):
            result = _git(
                ["ls-files", filename],
                self.cec_path,
                check=False
            )
            if result.stdout.strip() == filename:
                _git(["rm", "--cached", filename], self.cec_path, check=False)
                logger.info(f"Untracked {filename} (now gitignored)")

    # =====================================================
    # Metadata Management
    # =====================================================

    def refresh_metadata(self) -> dict:
        """Refresh extracted metadata from ComfyUI installation.

        Re-extracts builtins, folder paths, and model loader metadata for the current environment.
        Useful after upgrading ComfyUI or to fix missing metadata files
        for environments created before v0.3.12.

        Returns:
            dict with keys:
                - builtins_refreshed: bool
                - folder_paths_refreshed: bool
                - model_loaders_refreshed: bool
                - builtins_count: int (number of builtin nodes)
                - folder_mappings_count: int (number of folder mappings)
                - model_loaders_count: int (number of generated model loader nodes)

        Raises:
            ValueError: If ComfyUI installation is missing or invalid
        """
        from ..utils.builtin_extractor import extract_comfyui_builtins
        from ..utils.folder_paths_extractor import extract_folder_paths
        from ..utils.model_loader_extractor import extract_comfyui_model_loaders

        if not self.comfyui_path.exists():
            raise ValueError(f"ComfyUI not found at {self.comfyui_path}")

        result = {
            "builtins_refreshed": False,
            "folder_paths_refreshed": False,
            "model_loaders_refreshed": False,
            "builtins_count": 0,
            "folder_mappings_count": 0,
            "model_loaders_count": 0,
        }

        # Re-extract builtins
        builtins_path = self.cec_path / "comfyui_builtins.json"
        try:
            output = extract_comfyui_builtins(self.comfyui_path, builtins_path)
            result["builtins_refreshed"] = True
            result["builtins_count"] = output.get("metadata", {}).get("total_nodes", 0)
            logger.info(f"Refreshed comfyui_builtins.json ({result['builtins_count']} nodes)")
        except Exception as e:
            logger.warning(f"Failed to refresh builtins: {e}", exc_info=True)

        # Re-extract folder paths
        folder_paths_path = self.cec_path / "comfyui_folder_paths.json"
        try:
            output = extract_folder_paths(self.comfyui_path, folder_paths_path)
            result["folder_paths_refreshed"] = True
            result["folder_mappings_count"] = output.get("metadata", {}).get("total_folder_types", 0)
            logger.info(f"Refreshed comfyui_folder_paths.json ({result['folder_mappings_count']} folder types)")
        except Exception as e:
            logger.warning(f"Failed to refresh folder paths: {e}", exc_info=True)

        # Re-extract model loaders
        model_loaders_path = self.cec_path / "comfyui_model_loaders.json"
        try:
            output = extract_comfyui_model_loaders(self.comfyui_path, model_loaders_path)
            result["model_loaders_refreshed"] = True
            result["model_loaders_count"] = output.get("metadata", {}).get("total_model_loaders", 0)
            logger.info(
                f"Refreshed comfyui_model_loaders.json "
                f"({result['model_loaders_count']} model loaders)"
            )
        except Exception as e:
            logger.warning(f"Failed to refresh model loaders: {e}", exc_info=True)

        return result
