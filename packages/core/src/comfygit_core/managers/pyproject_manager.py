"""PyprojectManager - Handles all pyproject.toml file operations.

This module provides a clean, reusable interface for managing pyproject.toml files,
especially for UV-based Python projects.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import cached_property
from pathlib import Path
from typing import Any, cast

import tomlkit

from comfygit_core.models.manifest import EnvironmentManifestSnapshot

from ..logging.logging_config import get_logger
from ..manifest import (
    DependencyHandler,
    ModelHandler,
    NodeHandler,
    SyncConfigHandler,
    UVConfigHandler,
    WorkflowHandler,
)
from ..manifest.migrations import (
    strip_local_path_sources_from_config,
    strip_tracked_pytorch_config_from_config,
)
from ..manifest.overlays import (
    apply_uv_overlays_to_config,
    summarize_modified_overlay_fields,
)
from ..manifest.store import PyprojectStore
from ..models.overlay import OverlayConfig

logger = get_logger(__name__)


class PyprojectManager:
    """Manages pyproject.toml file operations for Python projects."""

    # Class-level call counter for tracking total loads across all instances
    _total_load_calls = 0

    def __init__(self, pyproject_path: Path):
        """Initialize the PyprojectManager.

        Args:
            pyproject_path: Path to the pyproject.toml file
        """
        self.path = pyproject_path
        self._store = PyprojectStore(pyproject_path)

    @cached_property
    def dependencies(self) -> DependencyHandler:
        """Get dependency handler."""
        return DependencyHandler(self)

    @cached_property
    def nodes(self) -> NodeHandler:
        """Get node handler."""
        return NodeHandler(self)

    @cached_property
    def uv_config(self) -> UVConfigHandler:
        """Get UV configuration handler."""
        return UVConfigHandler(self)

    @cached_property
    def workflows(self) -> WorkflowHandler:
        """Get workflow handler."""
        return WorkflowHandler(self)

    @cached_property
    def models(self) -> ModelHandler:
        """Get model handler."""
        return ModelHandler(self)

    @cached_property
    def sync_config(self) -> SyncConfigHandler:
        """Get sync configuration handler."""
        return SyncConfigHandler(self)

    # ===== Core Operations =====

    def ensure_system_uv_dependency(
        self,
        dependency: str = "uv>=0.11.8",
        group: str = "comfygit-system",
    ) -> bool:
        """Ensure uv remains a ComfyGit-managed system tool.

        Returns:
            True when the manifest changed, False when it already matched.
        """
        config = self.load()
        changed = False

        if not isinstance(config.get('dependency-groups'), dict):
            config['dependency-groups'] = tomlkit.table()
            changed = True

        def _as_dependency_list(value: Any) -> list[Any]:
            if value is None:
                return []
            if isinstance(value, str):
                return [value]
            try:
                return list(value)
            except TypeError:
                return [value]

        def _is_list_like(value: Any) -> bool:
            return not isinstance(value, str) and hasattr(value, "__iter__") and hasattr(value, "append")

        def _same_dependencies(left: list[Any], right: list[Any]) -> bool:
            return [str(item) for item in left] == [str(item) for item in right]

        def _name(spec: str) -> str:
            return self.uv_config._extract_package_name(spec)

        dependency_groups = cast(dict, config['dependency-groups'])
        existing_group_value = dependency_groups.get(group)
        group_deps = _as_dependency_list(existing_group_value)
        desired_group_deps = [dep for dep in group_deps if _name(str(dep)) != "uv"]
        desired_group_deps.append(dependency)
        if (
            group not in dependency_groups
            or not _is_list_like(existing_group_value)
            or not _same_dependencies(group_deps, desired_group_deps)
        ):
            dependency_groups[group] = desired_group_deps
            changed = True

        tool_config = config.get('tool')
        if not isinstance(tool_config, dict):
            tool_config = tomlkit.table()
            config['tool'] = tool_config
            changed = True
        uv_config = tool_config.get('uv')
        if not isinstance(uv_config, dict):
            uv_config = tomlkit.table()
            tool_config['uv'] = uv_config
            changed = True
        uv_config = cast(dict, uv_config)

        if 'constraint-dependencies' in uv_config:
            constraints = _as_dependency_list(uv_config.get('constraint-dependencies'))
            desired_constraints = [item for item in constraints if _name(str(item)) != "uv"]
            if desired_constraints:
                if (
                    not _is_list_like(uv_config.get('constraint-dependencies'))
                    or not _same_dependencies(constraints, desired_constraints)
                ):
                    uv_config['constraint-dependencies'] = desired_constraints
                    changed = True
            else:
                uv_config.pop('constraint-dependencies', None)
                changed = True

        existing_override_value = uv_config.get('override-dependencies')
        overrides = _as_dependency_list(existing_override_value)
        desired_overrides = [item for item in overrides if _name(str(item)) != "uv"]
        desired_overrides.append(dependency)
        if (
            'override-dependencies' not in uv_config
            or not _is_list_like(existing_override_value)
            or not _same_dependencies(overrides, desired_overrides)
        ):
            uv_config['override-dependencies'] = desired_overrides
            changed = True

        if changed:
            self.save(config)

        return changed

    def exists(self) -> bool:
        """Check if the pyproject.toml file exists."""
        return self._store.exists()

    def get_load_stats(self) -> dict:
        """Get statistics about pyproject.toml load operations.

        Returns:
            Dictionary with load statistics including:
            - instance_loads: Number of loads for this instance
            - total_loads: Total loads across all instances
        """
        stats = self._store.get_load_stats()
        PyprojectManager._total_load_calls = stats["total_loads"]
        return stats

    @classmethod
    def reset_load_stats(cls):
        """Reset class-level load statistics (useful for testing/benchmarking)."""
        PyprojectStore.reset_load_stats()
        cls._total_load_calls = 0

    def load(self, force_reload: bool = False) -> dict:
        """Load the pyproject.toml file with instance-level caching.

        Cache is automatically invalidated when the file's mtime changes.

        Args:
            force_reload: Force reload from disk even if cached

        Returns:
            The loaded configuration dictionary

        Raises:
            CDPyprojectNotFoundError: If the file doesn't exist
            CDPyprojectInvalidError: If the file is empty or invalid
        """
        config = self._store.load(force_reload=force_reload)
        PyprojectManager._total_load_calls = self._store.get_load_stats()["total_loads"]
        return config

    def get_manifest_snapshot(self, force_reload: bool = False) -> EnvironmentManifestSnapshot:
        """Return a typed read-only projection of the current manifest.

        The snapshot is derived from the same freshness-aware `load()` path as
        handler reads. Callers should request a new snapshot after any manifest
        mutation instead of retaining one as an authority.
        """
        return EnvironmentManifestSnapshot.from_toml_dict(
            self.load(force_reload=force_reload)
        )

    def save(self, config: dict | None = None) -> None:
        """Save the configuration to pyproject.toml.

        Automatically invalidates the cache to ensure fresh reads after save.

        Args:
            config: Configuration to save (uses cache if not provided)

        Raises:
            CDPyprojectError: If no configuration to save or write fails
        """
        self._store.save(config)

    @contextmanager
    def edit(self) -> Iterator[dict]:
        """Yield a mutable manifest document and save once on success.

        If the edit body raises, the tracked file is left untouched and the
        cached document is invalidated so later reads reload from disk.
        """
        config = self.load()
        try:
            yield config
        except Exception:
            self._store.reset_cache()
            raise
        else:
            self.save(config)

    def reset_lazy_handlers(self):
        """Clear all cached properties to force re-initialization."""
        cached_props = [
            name for name in dir(type(self))
            if isinstance(getattr(type(self), name, None), cached_property)
        ]
        for prop in cached_props:
            if prop in self.__dict__:
                del self.__dict__[prop]

        self._store.reset_cache()

    def get_sync_extras(self) -> list[str]:
        """Get default optional extras to install during sync."""
        return self.sync_config.get_extras()

    def set_sync_extras(self, extras: list[str]) -> None:
        """Set default optional extras to install during sync."""
        self.sync_config.set_extras(extras)

    def add_sync_extra(self, extra: str) -> bool:
        """Add a default sync extra (returns True if added)."""
        return self.sync_config.add_extra(extra)

    def remove_sync_extra(self, extra: str) -> bool:
        """Remove a default sync extra (returns True if removed)."""
        return self.sync_config.remove_extra(extra)

    def resolve_sync_extras(
        self,
        extras: list[str] | None,
        all_extras: bool
    ) -> tuple[list[str] | None, bool]:
        """Merge default sync extras with explicit extras."""
        return self.sync_config.resolve_extras(extras, all_extras)

    def snapshot(self) -> bytes:
        """Capture current pyproject.toml file contents for rollback.

        Returns:
            Raw file bytes
        """
        return self._store.snapshot()

    def restore(self, snapshot: bytes) -> None:
        """Restore pyproject.toml from a snapshot.

        Args:
            snapshot: Previously captured file bytes from snapshot()
        """
        self._store.restore(snapshot)
        self.reset_lazy_handlers()

    def _log_overlay_application_failure(
        self,
        effective_overlays: list[OverlayConfig],
        exc: Exception,
    ) -> None:
        logger.error("=== UV Overlay Application Failure ===")
        logger.error(
            "Overlays: %s",
            [overlay.name for overlay in effective_overlays],
        )
        try:
            summary = summarize_modified_overlay_fields(effective_overlays)
        except Exception:
            summary = {}
        logger.error("Overlay field summary: %s", summary)
        logger.error("Overlay application error: %s: %s", type(exc).__name__, exc)

    def apply_uv_overlays(
        self,
        overlays: list[OverlayConfig] | None = None,
    ) -> None:
        """Persist overlay-derived UV configuration into this pyproject.

        Use this for disposable or generated project files where the overlay
        materialization itself is the desired file state. Durable tracked
        manifests should not be passed here for local overlays; sync/run should
        first copy them into a disposable project.
        """
        effective_overlays = list(overlays or [])

        if not effective_overlays:
            return

        try:
            config = self.load()
            self._store.sanitize_workflow_contracts_for_toml(config)
            apply_uv_overlays_to_config(config, effective_overlays)
            self.save(config)
        except Exception as exc:
            self._log_overlay_application_failure(effective_overlays, exc)
            raise

    def strip_local_path_sources(self, config: dict | None = None) -> list[str]:
        """Remove uv sources with local filesystem paths.

        Returns list of removed package names.
        """
        config_to_use = config or self.load()
        removed = strip_local_path_sources_from_config(config_to_use)

        if removed and config is None:
            self.save(config_to_use)

        return removed

    def strip_pytorch_config(self) -> None:
        """Remove PyTorch-specific configuration from pyproject.toml.

        Removes:
            - PyTorch indexes from tool.uv.index (names containing 'pytorch')
            - PyTorch sources from tool.uv.sources (torch, torchvision, torchaudio)
            - PyTorch constraints from tool.uv.constraint-dependencies
            - torch_backend from tool.comfygit

        This is used during environment creation to ensure PyTorch config is not
        tracked in git, and during migration from schema v1 to v2.
        """
        from ..constants import PYTORCH_CORE_PACKAGES

        config = self.load()
        strip_tracked_pytorch_config_from_config(config, set(PYTORCH_CORE_PACKAGES))
        self.save(config)
        logger.debug("Stripped PyTorch config from pyproject.toml")

    def migrate_pytorch_config(self) -> bool:
        """Migrate from schema v1 to v2 by stripping embedded PyTorch config.

        Schema v1 had PyTorch config embedded in [tool.uv] section.
        Schema v2 materializes PyTorch config from .pytorch-backend only in disposable sync projects.

        This migration:
        1. Strips embedded [tool.uv] PyTorch config (indexes, sources, constraints)
        2. Removes torch_backend field from [tool.comfygit] if present
        3. Sets schema_version = 2

        Note: This does NOT create .pytorch-backend file. The user should
        explicitly set their preferred backend with 'cg env-config torch-backend set'.
        Until then, auto-detection will be used.

        Returns:
            True if migration was performed, False if already migrated
        """
        config = self.load()
        comfygit_config = config.get('tool', {}).get('comfygit', {})

        # Check if already migrated (schema v2+)
        schema_version = comfygit_config.get('schema_version', 1)
        if schema_version >= 2:
            logger.debug("Already at schema v2+, skipping migration")
            return False

        logger.info(f"Migrating pyproject from schema v{schema_version} to v2...")

        from ..constants import PYTORCH_CORE_PACKAGES

        # Strip PyTorch config and bump schema in one manifest write.
        strip_tracked_pytorch_config_from_config(config, set(PYTORCH_CORE_PACKAGES))
        if 'tool' not in config:
            config['tool'] = tomlkit.table()
        if 'comfygit' not in config['tool']:
            config['tool']['comfygit'] = tomlkit.table()
        comfygit_config = cast(dict[str, Any], config['tool']['comfygit'])
        comfygit_config['schema_version'] = 2
        self.save(config)

        # Verify the save worked
        verify_config = self.load(force_reload=True)
        saved_version = verify_config.get('tool', {}).get('comfygit', {}).get('schema_version')
        if saved_version != 2:
            logger.error(f"Migration verification FAILED: schema_version is {saved_version}, expected 2")
        else:
            logger.info("Migrated pyproject.toml to schema v2")

        return True
