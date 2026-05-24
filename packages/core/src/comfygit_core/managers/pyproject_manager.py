"""PyprojectManager - Handles all pyproject.toml file operations.

This module provides a clean, reusable interface for managing pyproject.toml files,
especially for UV-based Python projects.
"""
from __future__ import annotations

import logging
import re
import time
import traceback
from functools import cached_property
from pathlib import Path
from typing import Any, cast

import tomlkit
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from tomlkit.exceptions import TOMLKitError

from comfygit_core.models.manifest import EnvironmentManifestSnapshot
from comfygit_core.models.workflow_contract import toml_safe_contract_value

from ..logging.logging_config import get_logger
from ..manifest import (
    DependencyHandler,
    ModelHandler,
    NodeHandler,
    UVConfigHandler,
    WorkflowHandler,
)
from ..models.exceptions import CDPyprojectError, CDPyprojectInvalidError, CDPyprojectNotFoundError
from ..models.overlay import OverlayConfig
from ..utils.dependency_parser import parse_dependency_string

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
        self._instance_load_calls = 0  # Instance-level counter
        self._config_cache: dict | None = None
        self._cache_mtime: float | None = None

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
        return self.path.exists()

    def get_load_stats(self) -> dict:
        """Get statistics about pyproject.toml load operations.

        Returns:
            Dictionary with load statistics including:
            - instance_loads: Number of loads for this instance
            - total_loads: Total loads across all instances
        """
        return {
            "instance_loads": self._instance_load_calls,
            "total_loads": PyprojectManager._total_load_calls,
        }

    @classmethod
    def reset_load_stats(cls):
        """Reset class-level load statistics (useful for testing/benchmarking)."""
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
        if not self.exists():
            raise CDPyprojectNotFoundError(f"pyproject.toml not found at {self.path}")

        # Check cache validity via mtime
        current_mtime = self.path.stat().st_mtime

        if (not force_reload and
            self._config_cache is not None and
            self._cache_mtime == current_mtime):
            # Cache hit
            logger.debug("[PYPROJECT CACHE HIT] Using cached config")
            return self._config_cache

        # Cache miss - load from disk
        PyprojectManager._total_load_calls += 1
        self._instance_load_calls += 1

        debug_enabled = logger.isEnabledFor(logging.DEBUG)
        start_time = 0.0
        caller_info = "unknown"
        if debug_enabled:
            stack = traceback.extract_stack()
            caller_frame = stack[-2] if len(stack) >= 2 else None
            caller_info = f"{caller_frame.filename}:{caller_frame.lineno} in {caller_frame.name}" if caller_frame else "unknown"
            start_time = time.perf_counter()

        try:
            with open(self.path, encoding='utf-8') as f:
                config = tomlkit.load(f)
        except (OSError, TOMLKitError) as e:
            raise CDPyprojectInvalidError(f"Failed to parse pyproject.toml at {self.path}: {e}") from e

        if not config:
            raise CDPyprojectInvalidError(f"pyproject.toml is empty at {self.path}")

        # Cache the loaded config
        self._config_cache = config
        self._cache_mtime = current_mtime

        if debug_enabled:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(
                f"[PYPROJECT LOAD #{self._instance_load_calls}/{PyprojectManager._total_load_calls}] "
                f"Loaded pyproject.toml in {elapsed_ms:.2f}ms | "
                f"Called from: {caller_info}"
            )

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
        if config is None:
            raise CDPyprojectError("No configuration to save")

        self._sanitize_workflow_contracts_for_toml(config)

        # Clean up empty sections before saving
        self._cleanup_empty_sections(config)

        # Ensure proper spacing between major sections
        self._ensure_section_spacing(config)

        try:
            # Ensure parent directory exists
            self.path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.path, 'w', encoding='utf-8') as f:
                tomlkit.dump(config, f)
        except OSError as e:
            raise CDPyprojectError(f"Failed to write pyproject.toml to {self.path}: {e}") from e

        # Invalidate cache after save to ensure fresh reads
        self._config_cache = None
        self._cache_mtime = None

        logger.debug(f"Saved pyproject.toml to {self.path}")

    def _sanitize_workflow_contracts_for_toml(self, config: dict) -> bool:
        """Make workflow contract numeric fields safe for TOML writers.

        TOML integers are signed 64-bit. ComfyUI widgets may expose unsigned
        64-bit seed bounds, so oversized integers must be serialized as strings
        to keep pyproject.toml parseable by UV and other strict TOML readers.
        """
        changed = False
        workflows = (
            config.get("tool", {})
            .get("comfygit", {})
            .get("workflows", {})
        )
        if not isinstance(workflows, dict):
            return False

        for workflow_data in workflows.values():
            if not isinstance(workflow_data, dict):
                continue
            execution_contract = workflow_data.get("execution_contract")
            if not isinstance(execution_contract, dict):
                continue
            contracts = execution_contract.get("contracts", {})
            if not isinstance(contracts, dict):
                continue

            for contract_data in contracts.values():
                if not isinstance(contract_data, dict):
                    continue
                inputs = contract_data.get("inputs", [])
                if not isinstance(inputs, list):
                    continue

                for input_data in inputs:
                    if not isinstance(input_data, dict):
                        continue
                    for key in ("default", "min", "max"):
                        if key not in input_data:
                            continue
                        original_value = input_data[key]
                        safe_value = toml_safe_contract_value(original_value)
                        if safe_value != original_value or type(safe_value) is not type(original_value):
                            input_data[key] = safe_value
                            changed = True

        return changed

    def reset_lazy_handlers(self):
        """Clear all cached properties to force re-initialization."""
        cached_props = [
            name for name in dir(type(self))
            if isinstance(getattr(type(self), name, None), cached_property)
        ]
        for prop in cached_props:
            if prop in self.__dict__:
                del self.__dict__[prop]

        # Invalidate cache after save to ensure fresh reads
        self._config_cache = None
        self._cache_mtime = None

    def _cleanup_empty_sections(self, config: dict) -> None:
        """Recursively remove empty sections from config."""
        def _clean_dict(d: dict) -> bool:
            """Recursively clean dict, return True if dict became empty."""
            keys_to_remove = []
            for key, value in list(d.items()):
                if isinstance(value, dict):
                    if _clean_dict(value) or not value:
                        keys_to_remove.append(key)
            for key in keys_to_remove:
                del d[key]
            return not d

        _clean_dict(config)

    def _ensure_section_spacing(self, config: dict) -> None:
        """Ensure proper spacing between major sections in tool.comfygit.

        This adds visual separation between:
        - [tool.comfygit] metadata and workflows
        - workflows section and models section
        """
        if 'tool' not in config or 'comfygit' not in config['tool']:
            return

        comfygit = config['tool']['comfygit']

        # Track which sections exist
        has_metadata = any(k in comfygit for k in ['comfyui_version', 'python_version', 'manifest_state'])
        has_nodes = 'nodes' in comfygit
        has_workflows = 'workflows' in comfygit
        has_models = 'models' in comfygit

        # Only rebuild if we have workflows or models (need spacing)
        if not (has_workflows or has_models):
            return

        # Deep copy sections to strip any accumulated whitespace
        def deep_copy_table(obj):
            """Recursively copy tomlkit objects, preserving special types."""
            if isinstance(obj, dict):
                # Determine if inline table or regular table
                is_inline = hasattr(obj, '__class__') and 'InlineTable' in obj.__class__.__name__
                new_dict = tomlkit.inline_table() if is_inline else tomlkit.table()
                for k, v in obj.items():
                    # Skip whitespace items (empty keys)
                    if k == '':
                        continue
                    new_dict[k] = deep_copy_table(v)
                return new_dict
            elif isinstance(obj, list):
                # Check if this is a tomlkit array (preserve inline table items)
                is_tomlkit_array = hasattr(obj, '__class__') and 'Array' in obj.__class__.__name__
                if is_tomlkit_array:
                    new_array = tomlkit.array()
                    for item in obj:
                        # Preserve inline tables inside arrays
                        if hasattr(item, '__class__') and 'InlineTable' in item.__class__.__name__:
                            new_inline = tomlkit.inline_table()
                            for k, v in item.items():
                                new_inline[k] = deep_copy_table(v)
                            new_array.append(new_inline)
                        else:
                            new_array.append(deep_copy_table(item))
                    return new_array
                else:
                    return [deep_copy_table(item) for item in obj]
            else:
                return obj

        # Create a new table with sections in the correct order
        new_table = tomlkit.table()

        # Add metadata and non-reserved subtables first. Preserve unknown
        # fields so callers can add new top-level manifest flags/tables without
        # this formatter silently dropping them.
        for key, value in comfygit.items():
            if key in {"nodes", "workflows", "models"}:
                continue
            if key == "":
                continue
            new_table[key] = deep_copy_table(value)

        # Add nodes if it exists
        if has_nodes:
            new_table['nodes'] = deep_copy_table(comfygit['nodes'])

        # Add workflows with preceding newline if needed
        if has_workflows:
            if has_metadata or has_nodes:
                new_table.add(tomlkit.nl())
            new_table['workflows'] = deep_copy_table(comfygit['workflows'])

        # Add models with preceding newline if needed
        if has_models:
            if has_metadata or has_nodes or has_workflows:
                new_table.add(tomlkit.nl())
            new_table['models'] = deep_copy_table(comfygit['models'])

        # Replace the comfygit table
        config['tool']['comfygit'] = new_table

    @staticmethod
    def _normalize_extra(extra: str) -> str:
        """Normalize optional extras for comparison."""
        return extra.strip().lower().replace('_', '-')

    def _dedupe_extras(self, extras: list[str]) -> list[str]:
        """Normalize and deduplicate extras, preserving first-seen order."""
        seen = set()
        result = []
        for extra in extras:
            normalized = self._normalize_extra(extra)
            if not normalized or normalized in seen:
                continue
            result.append(normalized)
            seen.add(normalized)
        return result

    def get_sync_extras(self) -> list[str]:
        """Get default optional extras to install during sync."""
        config = self.load()
        return list(
            config.get("tool", {})
            .get("comfygit", {})
            .get("sync", {})
            .get("extras", [])
        )

    def set_sync_extras(self, extras: list[str]) -> None:
        """Set default optional extras to install during sync."""
        normalized = self._dedupe_extras(extras)
        config = self.load()
        config.setdefault("tool", {})
        config["tool"].setdefault("comfygit", {})

        if normalized:
            sync_config = config["tool"]["comfygit"].get("sync", {})
            sync_config["extras"] = normalized
            config["tool"]["comfygit"]["sync"] = sync_config
        else:
            sync_config = config["tool"]["comfygit"].get("sync", {})
            if isinstance(sync_config, dict):
                sync_config.pop("extras", None)
                if not sync_config:
                    config["tool"]["comfygit"].pop("sync", None)

        self.save(config)

    def add_sync_extra(self, extra: str) -> bool:
        """Add a default sync extra (returns True if added)."""
        current = self.get_sync_extras()
        updated = self._dedupe_extras(current + [extra])
        if updated == self._dedupe_extras(current):
            return False
        self.set_sync_extras(updated)
        return True

    def remove_sync_extra(self, extra: str) -> bool:
        """Remove a default sync extra (returns True if removed)."""
        target = self._normalize_extra(extra)
        if not target:
            return False
        current = self.get_sync_extras()
        updated = [e for e in current if self._normalize_extra(e) != target]
        if updated == current:
            return False
        self.set_sync_extras(updated)
        return True

    def resolve_sync_extras(
        self,
        extras: list[str] | None,
        all_extras: bool
    ) -> tuple[list[str] | None, bool]:
        """Merge default sync extras with explicit extras."""
        if all_extras:
            return None, True
        merged = self._dedupe_extras(self.get_sync_extras() + (extras or []))
        return (merged or None), False

    def snapshot(self) -> bytes:
        """Capture current pyproject.toml file contents for rollback.

        Returns:
            Raw file bytes
        """
        return self.path.read_bytes()

    def restore(self, snapshot: bytes) -> None:
        """Restore pyproject.toml from a snapshot.

        Args:
            snapshot: Previously captured file bytes from snapshot()
        """
        self.path.write_bytes(snapshot)
        # Reset lazy handlers so they reload from restored state
        self.reset_lazy_handlers()
        logger.debug("Restored pyproject.toml from snapshot")

    def _summarize_modified_overlay_fields(self, overlays: list[OverlayConfig]) -> dict[str, int]:
        summary = {
            "dependencies": 0,
            "sources": 0,
            "constraints": 0,
            "indexes": 0,
            "dependency_metadata": 0,
            "no_build_isolation_packages": 0,
            "override_dependencies": 0,
            "environments": 0,
        }

        for overlay in overlays:
            payload = overlay.to_uv_payload()
            for key in summary:
                value = payload.get(key)
                if isinstance(value, dict):
                    summary[key] += len(value)
                elif isinstance(value, list):
                    summary[key] += len(value)
                elif value:
                    summary[key] += 1

        return {
            key: count
            for key, count in summary.items()
            if count > 0
        }

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
            summary = self._summarize_modified_overlay_fields(effective_overlays)
        except Exception:
            summary = {}
        logger.error("Overlay field summary: %s", summary)
        logger.error("Overlay application error: %s: %s", type(exc).__name__, exc)

    def _apply_uv_overlays_to_config(
        self,
        config: dict,
        effective_overlays: list[OverlayConfig],
    ) -> None:
        if not effective_overlays:
            return

        self._sanitize_workflow_contracts_for_toml(config)

        # Strip tracked local path sources before local overlays are applied.
        if any(overlay.is_local for overlay in effective_overlays):
            self._strip_local_path_sources_from_config(config)

        from ..constants import PYTORCH_CORE_PACKAGES
        for overlay in effective_overlays:
            if overlay.kind == "pytorch":
                self._strip_pytorch_config_from_config(config, set(PYTORCH_CORE_PACKAGES))

            payload = overlay.to_uv_payload()
            self._inject_overlay_payload(config, payload)

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
            self._apply_uv_overlays_to_config(config, effective_overlays)
            self.save(config)
        except Exception as exc:
            self._log_overlay_application_failure(effective_overlays, exc)
            raise

    def strip_local_path_sources(self, config: dict | None = None) -> list[str]:
        """Remove uv sources with local filesystem paths.

        Returns list of removed package names.
        """
        config_to_use = config or self.load()
        removed = self._strip_local_path_sources_from_config(config_to_use)

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

        # Remove torch_backend from tool.comfygit
        if 'tool' in config and 'comfygit' in config['tool']:
            config['tool']['comfygit'].pop('torch_backend', None)

        # Remove PyTorch config from tool.uv
        if 'tool' in config and 'uv' in config['tool']:
            uv_config = config['tool']['uv']

            # Helper to safely delete keys from tomlkit containers
            # OutOfOrderTableProxy can raise NonExistentKey even when key appears present
            def safe_del(container: dict, key: str) -> None:
                try:
                    del container[key]
                except (KeyError, Exception):
                    # tomlkit.exceptions.NonExistentKey or similar
                    pass

            # Remove PyTorch indexes
            if 'index' in uv_config:
                indexes = uv_config['index']
                if isinstance(indexes, list):
                    uv_config['index'] = [
                        idx for idx in indexes
                        if 'pytorch' not in idx.get('name', '').lower()
                    ]
                    if not uv_config['index']:
                        safe_del(uv_config, 'index')

            # Remove PyTorch sources
            if 'sources' in uv_config:
                for pkg in PYTORCH_CORE_PACKAGES:
                    uv_config['sources'].pop(pkg, None)
                if not uv_config['sources']:
                    safe_del(uv_config, 'sources')

            # Remove PyTorch constraints
            if 'constraint-dependencies' in uv_config:
                constraints = uv_config['constraint-dependencies']
                uv_config['constraint-dependencies'] = [
                    c for c in constraints
                    if not any(pkg in c.lower() for pkg in PYTORCH_CORE_PACKAGES)
                ]
                if not uv_config['constraint-dependencies']:
                    safe_del(uv_config, 'constraint-dependencies')

            # Clean up empty uv section
            if not uv_config:
                safe_del(config['tool'], 'uv')

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

        # Strip PyTorch config from pyproject.toml
        self.strip_pytorch_config()

        # Bump schema version - reload to get the stripped config
        config = self.load(force_reload=True)
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

    def _strip_pytorch_config_from_config(self, config: dict, pytorch_packages: set[str]) -> None:
        """Strip PyTorch uv config from an in-memory config dict."""
        if 'tool' in config and 'uv' in config['tool']:
            uv_config = config['tool']['uv']

            # Remove PyTorch indexes
            if 'index' in uv_config:
                indexes = uv_config.get('index', [])
                if isinstance(indexes, list):
                    uv_config['index'] = [
                        idx for idx in indexes
                        if not any(p in idx.get('name', '').lower() for p in ['pytorch-', 'torch-'])
                    ]

            # Remove PyTorch sources
            if 'sources' in uv_config:
                sources = uv_config['sources']
                for pkg in pytorch_packages:
                    sources.pop(pkg, None)

            # Remove PyTorch constraints
            if 'constraint-dependencies' in uv_config:
                constraints = uv_config['constraint-dependencies']
                if isinstance(constraints, list):
                    uv_config['constraint-dependencies'] = [
                        c for c in constraints
                        if not any(pkg in c for pkg in pytorch_packages)
                    ]

    def _strip_local_path_sources_from_config(self, config: dict) -> list[str]:
        """Remove uv sources with local filesystem paths from a config dict."""
        uv_config = config.get('tool', {}).get('uv', {})
        sources = uv_config.get('sources', {})

        if not sources:
            return []

        def is_local_source(value: object) -> bool:
            if isinstance(value, dict):
                return "path" in value
            if isinstance(value, list):
                return any(is_local_source(item) for item in value)
            return False

        to_remove = []
        for pkg_name, source_config in list(sources.items()):
            if is_local_source(source_config):
                to_remove.append(pkg_name)
                sources.pop(pkg_name, None)

        if not to_remove:
            return []

        # Clean up empty sections (safe for tomlkit containers)
        def safe_del(container: dict, key: str) -> None:
            try:
                del container[key]
            except (KeyError, Exception):
                pass

        if not sources:
            safe_del(uv_config, 'sources')

        if not uv_config:
            safe_del(config.get('tool', {}), 'uv')

        return to_remove
    def _extract_dependency_key(self, requirement: str) -> str:
        normalized_requirement = requirement.strip()
        try:
            parsed = Requirement(normalized_requirement)
            return canonicalize_name(parsed.name)
        except Exception:
            pass

        try:
            package_name, _ = parse_dependency_string(normalized_requirement)
            return canonicalize_name(package_name)
        except Exception:
            match = re.match(r"^([A-Za-z0-9._-]+)", normalized_requirement)
            if not match:
                return normalized_requirement.lower()
            return canonicalize_name(match.group(1))

    def _to_aot(self, values: list[dict]) -> Any:
        aot = tomlkit.aot()
        for value in values:
            table = tomlkit.table()
            for key, item in value.items():
                table[key] = item
            aot.append(table)
        return aot

    def _merge_by_name_last_wins(
        self,
        existing: list[dict],
        new_items: list[dict],
        key_name: str,
    ) -> list[dict]:
        merged: list[dict] = [dict(item) for item in existing if isinstance(item, dict)]
        for item in new_items:
            if not isinstance(item, dict):
                continue
            key = item.get(key_name)
            if isinstance(key, str):
                merged = [candidate for candidate in merged if candidate.get(key_name) != key]
            merged.append(dict(item))
        return merged

    def _merge_specs_last_wins(self, existing: list[str], new_specs: list[str]) -> list[str]:
        merged = list(existing)
        for spec in new_specs:
            spec_key = self._extract_dependency_key(spec)
            merged = [value for value in merged if self._extract_dependency_key(value) != spec_key]
            merged.append(spec)
        return merged

    def _inject_overlay_payload(self, config: dict, payload: dict) -> None:
        if not payload:
            return

        if 'project' not in config:
            config['project'] = tomlkit.table()
        if 'dependencies' not in config['project']:
            config['project']['dependencies'] = []

        existing_project_dependencies = config['project'].get('dependencies', [])
        if not isinstance(existing_project_dependencies, list):
            existing_project_dependencies = [existing_project_dependencies] if existing_project_dependencies else []

        overlay_deps = [dep for dep in payload.get('dependencies', []) if isinstance(dep, str)]
        merged_deps = self._merge_specs_last_wins(
            [dep for dep in existing_project_dependencies if isinstance(dep, str)],
            overlay_deps,
        )
        config['project']['dependencies'] = merged_deps

        if 'tool' not in config:
            config['tool'] = tomlkit.table()
        if 'uv' not in config['tool']:
            config['tool']['uv'] = tomlkit.table()

        uv_config = cast(dict[str, Any], config['tool']['uv'])

        existing_indexes = uv_config.get('index', [])
        if not isinstance(existing_indexes, list):
            existing_indexes = [existing_indexes] if existing_indexes else []
        merged_indexes = self._merge_by_name_last_wins(
            existing_indexes,
            payload.get('indexes', []),
            key_name='name',
        )
        if merged_indexes:
            uv_config['index'] = self._to_aot(merged_indexes)

        existing_sources = uv_config.get('sources', {})
        if not isinstance(existing_sources, dict):
            existing_sources = {}
        if 'sources' not in uv_config:
            uv_config['sources'] = tomlkit.table()
        uv_sources = cast(dict[str, Any], uv_config['sources'])
        for package_name, source in payload.get('sources', {}).items():
            source_key = canonicalize_name(package_name)
            existing_key = next(
                (
                    key for key in list(uv_sources.keys())
                    if canonicalize_name(key) == source_key
                ),
                None,
            )
            if existing_key and existing_key != package_name:
                del uv_sources[existing_key]
            uv_sources[package_name] = source

        constraints = [c for c in payload.get('constraints', []) if isinstance(c, str)]
        if constraints:
            existing_constraints = uv_config.get('constraint-dependencies', [])
            if not isinstance(existing_constraints, list):
                existing_constraints = [existing_constraints] if existing_constraints else []
            uv_config['constraint-dependencies'] = self._merge_specs_last_wins(
                [c for c in existing_constraints if isinstance(c, str)],
                constraints,
            )

        metadata_entries = [
            entry for entry in payload.get('dependency_metadata', [])
            if isinstance(entry, dict)
        ]
        if metadata_entries:
            existing_metadata = uv_config.get('dependency-metadata', [])
            if not isinstance(existing_metadata, list):
                existing_metadata = [existing_metadata] if existing_metadata else []

            merged_metadata = [dict(entry) for entry in existing_metadata if isinstance(entry, dict)]
            for metadata in metadata_entries:
                package_name = metadata.get('name')
                if not isinstance(package_name, str):
                    merged_metadata.append(dict(metadata))
                    continue
                package_key = canonicalize_name(package_name)
                merged_metadata = [
                    item
                    for item in merged_metadata
                    if canonicalize_name(str(item.get('name', ''))) != package_key
                ]
                merged_metadata.append(dict(metadata))

            uv_config['dependency-metadata'] = self._to_aot(merged_metadata)

        no_build_isolation = [
            item for item in payload.get('no_build_isolation_packages', [])
            if isinstance(item, str)
        ]
        if no_build_isolation:
            existing_no_build = uv_config.get('no-build-isolation-package', [])
            if not isinstance(existing_no_build, list):
                existing_no_build = [existing_no_build] if existing_no_build else []
            merged_no_build = list(existing_no_build)
            seen_no_build = {
                canonicalize_name(item)
                for item in existing_no_build
                if isinstance(item, str)
            }
            for package_name in no_build_isolation:
                package_key = canonicalize_name(package_name)
                if package_key in seen_no_build:
                    continue
                merged_no_build.append(package_name)
                seen_no_build.add(package_key)
            uv_config['no-build-isolation-package'] = merged_no_build

        override_dependencies = [
            item for item in payload.get('override_dependencies', [])
            if isinstance(item, str)
        ]
        if override_dependencies:
            existing_override = uv_config.get('override-dependencies', [])
            if not isinstance(existing_override, list):
                existing_override = [existing_override] if existing_override else []
            uv_config['override-dependencies'] = self._merge_specs_last_wins(
                [item for item in existing_override if isinstance(item, str)],
                override_dependencies,
            )

        environments = [
            item for item in payload.get('environments', [])
            if isinstance(item, str)
        ]
        if environments:
            existing_environments = uv_config.get('environments', [])
            if not isinstance(existing_environments, list):
                existing_environments = [existing_environments] if existing_environments else []
            merged_environments = list(existing_environments)
            for environment in environments:
                if environment not in merged_environments:
                    merged_environments.append(environment)
            uv_config['environments'] = merged_environments
