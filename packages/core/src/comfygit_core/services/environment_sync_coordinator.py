"""Environment sync phase orchestration."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..constants import SYSTEM_DEPENDENCY_GROUP, SYSTEM_UV_DEPENDENCY
from ..logging.logging_config import get_logger
from ..models.sync import SyncResult
from ..utils.filesystem import rmtree

if TYPE_CHECKING:
    from ..core.environment import Environment
    from ..models.protocols import SyncCallbacks
    from ..models.workflow import BatchDownloadCallbacks, NodeInstallCallbacks

logger = get_logger(__name__)


class EnvironmentSyncCoordinator:
    """Coordinates the phases that reconcile an environment to local runtime state."""

    def __init__(self, environment: Environment) -> None:
        self.environment = environment

    def sync(
        self,
        *,
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
        """Apply manifest and local configuration state to the runtime."""
        env = self.environment
        result = SyncResult()

        # Migrate schema v1 -> v2 if needed and repair generated gitignore entries.
        env._ensure_schema_migrated()

        # Ensure package config exists and sync resolver policy into pyproject.toml.
        env.package_config.ensure_exists()
        env.pyproject.uv_config.set_exclude_dependencies(
            env.package_config.exclude_packages
        )
        env.pyproject.ensure_system_uv_dependency(
            dependency=SYSTEM_UV_DEPENDENCY,
            group=SYSTEM_DEPENDENCY_GROUP,
        )

        extras, all_extras = env.pyproject.resolve_sync_extras(extras, all_extras)

        logger.info("Syncing environment...")

        try:
            sync_result = env.uv_manager.sync_dependencies_progressive(
                dry_run=dry_run,
                callbacks=sync_callbacks,
                verbose=verbose,
                pytorch_manager=env.pytorch_manager,
                overlay_names=overlay_names,
                backend_override=backend_override,
                extras=extras,
                all_extras=all_extras,
            )
            result.packages_synced = sync_result.packages_synced
            result.dependency_groups_installed.extend(
                sync_result.dependency_groups_installed
            )
            result.dependency_groups_failed.extend(sync_result.dependency_groups_failed)
            result.dependency_groups_skipped.extend(sync_result.dependency_groups_skipped)
        except Exception as e:
            # Progressive sync handles optional groups gracefully. Only base or
            # required groups should normally reach this failure path.
            logger.error(f"Package sync failed: {e}")
            result.errors.append(f"Package sync failed: {e}")
            result.success = False

        if not dry_run:
            self._remove_version_mismatched_nodes(result)

        try:
            env.node_manager.sync_nodes_to_filesystem(
                remove_extra=remove_extra_nodes and not dry_run,
                callbacks=node_callbacks,
            )
        except Exception as e:
            logger.error(f"Node sync failed: {e}")
            result.errors.append(f"Node sync failed: {e}")
            result.success = False

        self._sync_staged_node_dependencies(
            result,
            dry_run=dry_run,
            verbose=verbose,
            overlay_names=overlay_names,
            backend_override=backend_override,
            extras=extras,
            all_extras=all_extras,
        )
        self._restore_workflows(result, dry_run=dry_run, preserve_workflows=preserve_workflows)
        self._handle_missing_models(
            result,
            dry_run=dry_run,
            model_strategy=model_strategy,
            model_callbacks=model_callbacks,
        )
        self._configure_model_symlink(result)
        self._migrate_user_content_if_needed(result)
        self._configure_user_content_symlinks(result)
        self._mark_complete_if_success(result, dry_run=dry_run)

        if result.success:
            logger.info("Successfully synced environment")
        else:
            logger.warning(f"Sync completed with {len(result.errors)} errors")

        return result

    def _remove_version_mismatched_nodes(self, result: SyncResult) -> None:
        env = self.environment
        try:
            current_status = env.status()
            for mismatch in current_status.comparison.version_mismatches:
                node_name = mismatch["name"]
                node_path = env.custom_nodes_path / node_name
                if node_path.exists():
                    logger.info(
                        "Removing node with wrong version: %s (%s -> %s)",
                        node_name,
                        mismatch["actual"],
                        mismatch["expected"],
                    )
                    rmtree(node_path)
        except Exception as e:
            logger.warning(f"Could not check/fix version mismatches: {e}")

    def _sync_staged_node_dependencies(
        self,
        result: SyncResult,
        *,
        dry_run: bool,
        verbose: bool,
        overlay_names: list[str] | None,
        backend_override: str | None,
        extras: list[str] | None,
        all_extras: bool,
    ) -> None:
        if dry_run:
            return

        env = self.environment
        staged_node_groups: list[str] = []
        try:
            staged_node_groups = env.node_manager.provision_missing_node_dependencies()
            if not staged_node_groups:
                return

            logger.info(
                "Syncing %d staged node dependency group(s)",
                len(staged_node_groups),
            )
            env.uv_manager.sync_project(
                verbose=verbose,
                pytorch_manager=env.pytorch_manager,
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

    def _restore_workflows(
        self,
        result: SyncResult,
        *,
        dry_run: bool,
        preserve_workflows: bool,
    ) -> None:
        if dry_run or preserve_workflows:
            return

        env = self.environment
        logger.debug("Restoring workflows from .cec/")
        try:
            env.workflow_manager.restore_all_from_cec()
            logger.info("Restored workflows from .cec/")
        except Exception as e:
            logger.warning(f"Failed to restore workflows: {e}")
            result.errors.append(f"Workflow restore failed: {e}")

    def _handle_missing_models(
        self,
        result: SyncResult,
        *,
        dry_run: bool,
        model_strategy: str,
        model_callbacks: BatchDownloadCallbacks | None,
    ) -> None:
        if dry_run or model_strategy == "skip":
            return

        env = self.environment
        try:
            workflows_with_intents = env.model_manager.prepare_import_with_model_strategy(
                strategy=model_strategy
            )

            if not workflows_with_intents:
                return

            logger.info(f"Downloading models for {len(workflows_with_intents)} workflow(s)")

            # prepare_import_with_model_strategy() may update pyproject model entries.
            # Invalidate per-workflow cache entries so resolve_workflow() sees fresh
            # download intents instead of stale session-cached resolutions.
            for workflow_name in workflows_with_intents:
                env.workflow_cache.invalidate(env.name, workflow_name)

            from ..strategies.auto import AutoModelStrategy, AutoNodeStrategy

            for workflow_name in workflows_with_intents:
                try:
                    logger.debug(f"Resolving workflow: {workflow_name}")
                    resolution_result = env.resolve_workflow(
                        name=workflow_name,
                        model_strategy=AutoModelStrategy(),
                        node_strategy=AutoNodeStrategy(),
                        download_callbacks=model_callbacks,
                    )

                    for download_result in resolution_result.download_results:
                        if download_result.success:
                            result.models_downloaded.append(download_result.filename)
                        else:
                            result.models_failed.append(
                                (
                                    download_result.filename,
                                    download_result.error or "Download failed",
                                )
                            )

                except Exception as e:
                    logger.error(f"Failed to resolve {workflow_name}: {e}", exc_info=True)
                    result.errors.append(f"Failed to resolve {workflow_name}: {e}")

        except Exception as e:
            logger.warning(f"Model download failed: {e}", exc_info=True)
            result.errors.append(f"Model download failed: {e}")

    def _configure_model_symlink(self, result: SyncResult) -> None:
        try:
            self.environment.model_symlink_manager.create_symlink()
            result.model_paths_configured = True
        except Exception as e:
            logger.warning(f"Failed to ensure model symlink: {e}")
            result.errors.append(f"Model symlink configuration failed: {e}")

    def _migrate_user_content_if_needed(self, result: SyncResult) -> None:
        env = self.environment
        needs_migration = False
        if env.comfyui_path.exists():
            from ..utils.symlink_utils import is_link

            input_path = env.comfyui_path / "input"
            output_path = env.comfyui_path / "output"

            if input_path.exists() and not is_link(input_path):
                needs_migration = True
            if output_path.exists() and not is_link(output_path):
                needs_migration = True

        if not needs_migration:
            return

        logger.info("Detected pre-symlink environment, migrating user data...")
        try:
            migration_stats = env.user_content_manager.migrate_existing_data()
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

    def _configure_user_content_symlinks(self, result: SyncResult) -> None:
        env = self.environment
        try:
            env.user_content_manager.create_directories()
            env.user_content_manager.create_symlinks()
            logger.debug("User content symlinks configured")
        except Exception as e:
            logger.warning(f"Failed to ensure user content symlinks: {e}")
            result.errors.append(f"User content symlink configuration failed: {e}")

    def _mark_complete_if_success(self, result: SyncResult, *, dry_run: bool) -> None:
        if not result.success or dry_run:
            return

        from ..utils.environment_cleanup import mark_environment_complete

        mark_environment_complete(self.environment.cec_path)
        logger.debug("Marked environment as complete")
