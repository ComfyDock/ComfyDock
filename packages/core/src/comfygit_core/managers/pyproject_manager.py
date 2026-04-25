"""PyprojectManager - Handles all pyproject.toml file operations.

This module provides a clean, reusable interface for managing pyproject.toml files,
especially for UV-based Python projects.
"""
from __future__ import annotations

import hashlib
import re
import threading
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from tomlkit.exceptions import TOMLKitError

from comfygit_core.models.manifest import (
    ManifestModel,
    ManifestWorkflowModel,
    WorkflowExecutionContract,
)

from ..logging.logging_config import get_logger
from ..models.exceptions import CDPyprojectError, CDPyprojectInvalidError, CDPyprojectNotFoundError
from ..models.overlay import OverlayConfig

if TYPE_CHECKING:
    from ..models.shared import NodeInfo
    from .pytorch_backend_manager import PyTorchBackendManager

from ..utils.dependency_parser import parse_dependency_string

logger = get_logger(__name__)


class PyprojectManager:
    """Manages pyproject.toml file operations for Python projects."""

    # Class-level call counter for tracking total loads across all instances
    _total_load_calls = 0
    # Serialize temporary UV injection per pyproject path across manager instances.
    _injection_locks: dict[str, threading.RLock] = {}
    _injection_locks_guard = threading.Lock()

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
        import time
        import traceback

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

        # Get caller info for tracking where loads are coming from
        stack = traceback.extract_stack()
        caller_frame = stack[-2] if len(stack) >= 2 else None
        caller_info = f"{caller_frame.filename}:{caller_frame.lineno} in {caller_frame.name}" if caller_frame else "unknown"

        # Start timing
        start_time = time.perf_counter()

        try:
            with open(self.path, encoding='utf-8') as f:
                config = tomlkit.load(f)
        except (OSError, TOMLKitError) as e:
            raise CDPyprojectInvalidError(f"Failed to parse pyproject.toml at {self.path}: {e}")

        if not config:
            raise CDPyprojectInvalidError(f"pyproject.toml is empty at {self.path}")

        # Cache the loaded config
        self._config_cache = config
        self._cache_mtime = current_mtime

        # Calculate elapsed time
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Log with detailed metrics
        logger.debug(
            f"[PYPROJECT LOAD #{self._instance_load_calls}/{PyprojectManager._total_load_calls}] "
            f"Loaded pyproject.toml in {elapsed_ms:.2f}ms | "
            f"Called from: {caller_info}"
        )

        return config


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
            raise CDPyprojectError(f"Failed to write pyproject.toml to {self.path}: {e}")

        # Invalidate cache after save to ensure fresh reads
        self._config_cache = None
        self._cache_mtime = None

        logger.debug(f"Saved pyproject.toml to {self.path}")

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

        # Add metadata fields first
        for key in ['schema_version', 'comfyui_version', 'python_version', 'manifest_state']:
            if key in comfygit:
                new_table[key] = comfygit[key]

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

    def get_manifest_state(self) -> str:
        """Get the current manifest state.

        Returns:
            'local' or 'exportable'
        """
        config = self.load()
        if 'tool' in config and 'comfygit' in config['tool']:
            return config['tool']['comfygit'].get('manifest_state', 'local')
        return 'local'

    def set_manifest_state(self, state: str) -> None:
        """Set the manifest state.

        Args:
            state: 'local' or 'exportable'
        """
        if state not in ('local', 'exportable'):
            raise ValueError(f"Invalid manifest state: {state}")

        config = self.load()
        if 'tool' not in config:
            config['tool'] = {}
        if 'comfygit' not in config['tool']:
            config['tool']['comfygit'] = {}

        config['tool']['comfygit']['manifest_state'] = state
        self.save(config)
        logger.info(f"Set manifest state to: {state}")

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

    def pytorch_injection_context(
        self,
        pytorch_manager: PyTorchBackendManager,
        backend_override: str | None = None,
    ):
        """Context manager that temporarily injects PyTorch config during sync.

        This pattern allows syncing with platform-specific PyTorch configuration
        without persisting it to the tracked pyproject.toml.

        Usage:
            with pyproject.pytorch_injection_context(pytorch_manager):
                uv.sync_project()  # Sync happens with PyTorch config injected

        Args:
            pytorch_manager: PyTorchBackendManager instance for config generation
            backend_override: Override backend instead of reading from file (e.g., "cu128")

        Yields:
            None - the context manager just handles inject/restore
        """
        pytorch_overlay = self._pytorch_manager_to_overlay(
            pytorch_manager,
            backend_override=backend_override,
        )
        return self.uv_injection_context(
            overlays=[pytorch_overlay] if pytorch_overlay else None,
        )

    def _get_injection_lock(self) -> threading.RLock:
        path_key = str(self.path.resolve())
        with self._injection_locks_guard:
            lock = self._injection_locks.get(path_key)
            if lock is None:
                lock = threading.RLock()
                self._injection_locks[path_key] = lock
            return lock

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
            payload = overlay.to_injection_payload()
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

    def uv_injection_context(
        self,
        overlays: list[OverlayConfig] | None = None,
    ):
        """Context manager that temporarily injects UV config during sync.

        Uses a unified overlay pipeline for all temporary injection.
        """
        from contextlib import contextmanager

        @contextmanager
        def _injection_context():
            effective_overlays = list(overlays or [])

            if not effective_overlays:
                yield
                return

            with self._get_injection_lock():
                # Capture original content before any modifications
                original_content = self.path.read_text(encoding="utf-8")

                try:
                    config = self.load()

                    # Strip tracked local path sources before local overlays are applied.
                    if any(overlay.is_local for overlay in effective_overlays):
                        self._strip_local_path_sources_from_config(config)

                    from ..constants import PYTORCH_CORE_PACKAGES
                    for overlay in effective_overlays:
                        if overlay.kind == "pytorch":
                            self._strip_pytorch_config_from_config(config, PYTORCH_CORE_PACKAGES)

                        payload = overlay.to_injection_payload()
                        self._inject_overlay_payload(config, payload)

                    self.save(config)

                    yield

                except Exception as exc:
                    logger.error("=== UV Sync Failure ===")
                    logger.error(
                        "Overlays: %s",
                        [overlay.name for overlay in effective_overlays],
                    )
                    try:
                        summary = self._summarize_modified_overlay_fields(effective_overlays)
                    except Exception:
                        summary = {}
                    logger.error("Overlay field summary: %s", summary)
                    logger.error("Injection error: %s: %s", type(exc).__name__, exc)
                    raise

                finally:
                    # ALWAYS restore original content
                    self.path.write_text(original_content, encoding="utf-8")
                    # Invalidate cache to ensure fresh reads
                    self._config_cache = None
                    self._cache_mtime = None
                    logger.debug("Restored original pyproject.toml after UV injection")

        return _injection_context()

    def _pytorch_manager_to_overlay(
        self,
        pytorch_manager: PyTorchBackendManager,
        backend_override: str | None = None,
    ) -> OverlayConfig | None:
        config = self.load()
        python_version = config.get("tool", {}).get("comfygit", {}).get("python_version")
        pytorch_config = pytorch_manager.get_pytorch_config(
            backend_override=backend_override,
            python_version=python_version,
        )
        if not pytorch_config:
            return None
        return OverlayConfig(
            name=".pytorch",
            path=self.path.parent / ".pytorch-backend",
            description="Auto-generated PyTorch backend overlay",
            kind="pytorch",
            requires=[],
            is_local=True,
            dependencies=[],
            sources=dict(pytorch_config.get("sources", {})),
            settings={},
            dependency_metadata=[],
            constraints=list(pytorch_config.get("constraints", [])),
            indexes=list(pytorch_config.get("indexes", [])),
        )

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
        Schema v2 uses runtime injection from .pytorch-backend file.

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
        config['tool']['comfygit']['schema_version'] = 2
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

    def _to_aot(self, values: list[dict]) -> tomlkit.items.AoT:
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

        uv_config = config['tool']['uv']

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
        for package_name, source in payload.get('sources', {}).items():
            source_key = canonicalize_name(package_name)
            existing_key = next(
                (
                    key for key in list(uv_config['sources'].keys())
                    if canonicalize_name(key) == source_key
                ),
                None,
            )
            if existing_key and existing_key != package_name:
                del uv_config['sources'][existing_key]
            uv_config['sources'][package_name] = source

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


class BaseHandler:
    """Base handler providing common functionality."""

    def __init__(self, manager: PyprojectManager):
        self.manager = manager

    def load(self) -> dict:
        """Load configuration from manager."""
        return self.manager.load()

    def save(self, config: dict) -> None:
        """Save configuration through manager.

        Raises:
            CDPyprojectError
        """
        self.manager.save(config)

    def ensure_section(self, config: dict, *path: str) -> dict:
        """Ensure a nested section exists in config."""
        current = config
        for key in path:
            if key not in current:
                current[key] = tomlkit.table()
            current = current[key]
        return current

    def clean_empty_sections(self, config: dict, *path: str) -> None:
        """Clean up empty sections by removing them from bottom up."""
        if not path:
            return

        # Navigate to parent of the last key
        current = config
        for key in path[:-1]:
            if key not in current:
                return
            current = current[key]

        # Check if the final key exists and is empty
        final_key = path[-1]
        if final_key in current and not current[final_key]:
            del current[final_key]
            # Recursively clean parent if it becomes empty (except top-level sections)
            if len(path) > 2 and not current:
                self.clean_empty_sections(config, *path[:-1])


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
        from ..utils.dependency_parser import parse_dependency_string

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

        # Find and remove constraint by package name
        for i, existing in enumerate(constraints):
            if self._extract_package_name(existing) == package_name.lower():
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

    def ensure_exclude_dependencies(self, packages: list[str]) -> None:
        """Ensure packages are in exclude-dependencies list.

        Called during sync to ensure exclusions are applied even for
        environments created before this feature.

        Args:
            packages: List of package names to exclude
        """
        config = self.load()
        self.ensure_section(config, 'tool', 'uv')

        current = set(config['tool']['uv'].get('exclude-dependencies', []))
        to_add = set(packages) - current

        if to_add:
            all_exclusions = sorted(current | set(packages))
            config['tool']['uv']['exclude-dependencies'] = all_exclusions
            self.save(config)
            logger.info(f"Added package exclusions: {sorted(to_add)}")

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


class NodeHandler(BaseHandler):
    """Handles custom node management."""

    def add(self, node_info: NodeInfo, node_identifier: str | None) -> None:
        """Add a custom node to the pyproject.toml."""
        config = self.load()
        identifier = node_identifier or (node_info.registry_id if node_info.registry_id else node_info.name)

        # Only create nodes section when actually adding a node
        self.ensure_section(config, 'tool', 'comfygit', 'nodes')

        # Build node data, excluding any None values (tomlkit requirement)
        filtered_data = {k: v for k, v in node_info.__dict__.copy().items() if v is not None}

        # Create a proper tomlkit table for better formatting
        node_table = tomlkit.table()
        for key, value in filtered_data.items():
            node_table[key] = value

        # Add node to configuration
        config['tool']['comfygit']['nodes'][identifier] = node_table

        logger.info(f"Added custom node: {identifier}")
        self.save(config)

    def add_development(self, name: str) -> None:
        """Add a development node (version='dev')."""
        from ..models.shared import NodeInfo
        node_info = NodeInfo(
            name=name,
            version='dev',
            source='development'
        )
        self.add(node_info, name)

    # def is_development(self, identifier: str) -> bool:
    #     """Check if a node is a development node."""
    #     nodes = self.get_existing()
    #     node = nodes.get(identifier)
    #     return node and hasattr(node, 'version') and node.version == 'dev'

    def get_existing(self) -> dict[str, NodeInfo]:
        """Get all existing custom nodes from pyproject.toml."""
        from ..models.shared import NodeInfo
        config = self.load()
        nodes_data = config.get('tool', {}).get('comfygit', {}).get('nodes', {})

        result = {}
        for identifier, node_data in nodes_data.items():
            result[identifier] = NodeInfo(
                name=node_data.get('name') or identifier,
                repository=node_data.get('repository'),
                registry_id=node_data.get('registry_id'),
                version=node_data.get('version'),
                source=node_data.get('source', 'unknown'),
                download_url=node_data.get('download_url'),
                dependency_sources=node_data.get('dependency_sources'),
                criticality=node_data.get('criticality', 'required'),
                branch=node_data.get('branch'),
                pinned_commit=node_data.get('pinned_commit'),
            )

        return result

    def set_criticality(self, node_identifier: str, criticality: str) -> bool:
        """Set package-level custom-node criticality.

        Criticality is intentionally user-declared package metadata. Workflow graph
        analysis must not infer or mutate it.
        """
        from ..models.shared import normalize_node_criticality

        normalized = normalize_node_criticality(criticality)
        config = self.load()
        nodes = config.get('tool', {}).get('comfygit', {}).get('nodes', {})

        if node_identifier not in nodes:
            return False

        nodes[node_identifier]['criticality'] = normalized
        self.save(config)
        logger.debug("Set custom node criticality: %s -> %s", node_identifier, normalized)
        return True

    def remove(self, node_identifier: str) -> bool:
        """Remove a custom node and its associated dependency group."""
        config = self.load()
        removed = False

        # Get existing nodes to find the one to remove
        existing_nodes = self.get_existing()
        if node_identifier not in existing_nodes:
            return False

        node_info = existing_nodes[node_identifier]

        # Generate the hash-based group name that was used during add
        fallback_identifier = node_info.registry_id if node_info.registry_id else node_info.name
        group_name = self.generate_group_name(node_info, fallback_identifier)

        # Remove from dependency-groups using the hash-based group name
        if 'dependency-groups' in config and group_name in config['dependency-groups']:
            del config['dependency-groups'][group_name]
            removed = True
            logger.debug(f"Removed dependency group: {group_name}")

        # Remove from nodes using the original identifier
        if ('tool' in config and 'comfygit' in config['tool'] and
            'nodes' in config['tool']['comfygit'] and
            node_identifier in config['tool']['comfygit']['nodes']):
            del config['tool']['comfygit']['nodes'][node_identifier]
            removed = True
            logger.debug(f"Removed node info: {node_identifier}")

        if removed:
            # Clean up empty sections
            self.clean_empty_sections(config, 'tool', 'comfygit', 'nodes')
            self.save(config)
            logger.info(f"Removed custom node: {node_identifier}")

        return removed

    @staticmethod
    def generate_group_name(node_info: NodeInfo, fallback_identifier: str) -> str:
        """Generate a collision-resistant group name for a custom node."""
        # Use node name as base, fallback to identifier
        base_name = node_info.name or fallback_identifier

        # Normalize the base name (similar to what UV would do)
        normalized = re.sub(r'[^a-z0-9]+', '-', base_name.lower()).strip('-')

        # Generate hash from repository URL (most unique identifier) or fallback
        hash_source = node_info.repository or fallback_identifier
        hash_digest = hashlib.sha256(hash_source.encode()).hexdigest()[:8]

        return f"{normalized}-{hash_digest}"


# DevNodeHandler removed - development nodes now handled by NodeHandler with version='dev'


class WorkflowHandler(BaseHandler):
    """Handles workflow model resolutions and tracking."""

    @staticmethod
    def _ensure_workflow_entry(config: dict, workflow_name: str) -> dict:
        """Ensure workflow table and path exist, then return the workflow table."""
        workflows = config.setdefault('tool', {}).setdefault('comfygit', {}).setdefault('workflows', {})
        workflow = workflows.get(workflow_name)

        if workflow is None:
            workflow = tomlkit.table()
            workflows[workflow_name] = workflow

        if 'path' not in workflow:
            workflow['path'] = f"workflows/{workflow_name}.json"

        return workflow

    def get_workflow(self, name: str) -> dict | None:
        """Get a workflow from pyproject.toml."""
        try:
            config = self.load()
            return config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(name, None)
        except Exception:
            logger.error(f"Failed to load config for workflow: {name}")
            return None

    def add_workflow(self, name: str) -> None:
        """Add a new workflow to the pyproject.toml."""
        config = self.load()
        self._ensure_workflow_entry(config, name)
        logger.info(f"Added new workflow: {name}")
        self.save(config)

    def get_execution_contract(
        self,
        workflow_name: str,
        config: dict | None = None
    ) -> WorkflowExecutionContract | None:
        """Get the saved execution contract for a workflow."""
        try:
            if config is None:
                config = self.load()
            workflow_data = config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(workflow_name, {})
            contract_data = workflow_data.get('execution_contract')
            if not contract_data:
                return None
            return WorkflowExecutionContract.from_toml_dict(contract_data)
        except Exception as e:
            logger.debug(f"Error loading execution contract for '{workflow_name}': {e}")
            return None

    def set_execution_contract(
        self,
        workflow_name: str,
        contract: WorkflowExecutionContract,
        config: dict | None = None
    ) -> None:
        """Create or replace the saved execution contract for a workflow."""
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflow = self._ensure_workflow_entry(config, workflow_name)
        workflow['execution_contract'] = contract.to_toml_dict()

        if not is_batch:
            self.save(config)

        logger.debug(f"Set execution contract for workflow '{workflow_name}'")

    def remove_execution_contract(
        self,
        workflow_name: str,
        config: dict | None = None
    ) -> bool:
        """Remove the saved execution contract for a workflow."""
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflow = config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(workflow_name, {})
        if 'execution_contract' not in workflow:
            return False

        del workflow['execution_contract']

        if not is_batch:
            self.save(config)

        logger.debug(f"Removed execution contract for workflow '{workflow_name}'")
        return True

    def get_workflow_models(
        self,
        workflow_name: str,
        config: dict | None = None
    ) -> list[ManifestWorkflowModel]:
        """Get all models for a workflow.

        Args:
            workflow_name: Workflow name
            config: Optional in-memory config for batched reads. If None, loads from disk.

        Returns:
            List of ManifestWorkflowModel objects (resolved and unresolved)
        """
        try:
            if config is None:
                config = self.load()
            workflow_data = config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(workflow_name, {})
            models_data = workflow_data.get('models', [])

            return [ManifestWorkflowModel.from_toml_dict(m) for m in models_data]
        except Exception as e:
            logger.debug(f"Error loading workflow models for '{workflow_name}': {e}")
            return []

    def set_workflow_models(
        self,
        workflow_name: str,
        models: list[ManifestWorkflowModel],
        config: dict | None = None
    ) -> None:
        """Set all models for a workflow (unified list).

        Args:
            workflow_name: Workflow name
            models: List of ManifestWorkflowModel objects (resolved and unresolved)
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.
        """
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflow = self._ensure_workflow_entry(config, workflow_name)

        # Serialize to array of tables
        models_array = []
        for model in models:
            model_dict = model.to_toml_dict()
            # Convert to inline table for compact representation
            models_array.append(model_dict)

        workflow['models'] = models_array

        if not is_batch:
            self.save(config)

        logger.debug(f"Set {len(models)} model(s) for workflow '{workflow_name}'")

    def add_workflow_model(
        self,
        workflow_name: str,
        model: ManifestWorkflowModel
    ) -> None:
        """Add or update a single model in workflow (progressive write).

        Args:
            workflow_name: Workflow name
            model: ManifestWorkflowModel to add or update

        Note:
            - If same node reference exists, replaces/upgrades that entry
            - If model with same hash exists, merges nodes
            - Otherwise, appends as new model
        """
        existing = self.get_workflow_models(workflow_name)

        # Build set of node references in new model
        new_refs = {(n.node_id, n.widget_index) for n in model.nodes}

        # Check for overlap with existing models
        updated = False
        for i, existing_model in enumerate(existing):
            existing_refs = {(n.node_id, n.widget_index) for n in existing_model.nodes}

            # If any node references overlap, this is a resolution of an existing entry
            if new_refs & existing_refs:
                if model.hash:
                    # Resolved version replaces unresolved
                    existing[i] = model
                    logger.debug(f"Replaced unresolved model '{existing_model.filename}' with resolved '{model.filename}'")
                else:
                    # Both unresolved - merge nodes and update mutable fields
                    non_overlapping = [n for n in model.nodes if (n.node_id, n.widget_index) not in existing_refs]
                    existing_model.nodes.extend(non_overlapping)
                    existing_model.criticality = model.criticality
                    existing_model.status = model.status
                    # Update download intent fields if present
                    if model.sources:
                        existing_model.sources = model.sources
                    if model.relative_path:
                        existing_model.relative_path = model.relative_path
                    logger.debug(f"Updated unresolved model '{existing_model.filename}' with {len(non_overlapping)} new ref(s)")
                updated = True
                break

            # Fallback: hash matching (for models resolved to same file from different nodes)
            elif model.hash and existing_model.hash == model.hash:
                non_overlapping = [n for n in model.nodes if (n.node_id, n.widget_index) not in existing_refs]
                existing_model.nodes.extend(non_overlapping)
                logger.debug(f"Merged {len(non_overlapping)} new node(s) into existing model '{model.filename}'")
                updated = True
                break

        if not updated:
            # Completely new model
            existing.append(model)
            logger.debug(f"Added new model '{model.filename}' to workflow '{workflow_name}'")

        self.set_workflow_models(workflow_name, existing)


    def get_all_with_resolutions(self) -> dict:
        """Get all workflows that have model resolutions."""
        try:
            config = self.load()
            return config.get('tool', {}).get('comfygit', {}).get('workflows', {})
        except Exception:
            return {}

    def set_node_packs(self, name: str, node_pack_ids: set[str] | None, config: dict | None = None) -> None:
        """Set node pack references for a workflow.

        Args:
            name: Workflow name
            node_pack_ids: List of node pack identifiers (e.g., ["comfyui-akatz-nodes"]) | None which clears node packs
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.
        """
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflow = self._ensure_workflow_entry(config, name)
        if not node_pack_ids:
            if 'nodes' in workflow:
                logger.info(f"Clearing node packs for workflow: {name}")
                del workflow['nodes']
        else:
            logger.info(f"Set {len(node_pack_ids)} node pack(s) for workflow: {name}")
            workflow['nodes'] = sorted(node_pack_ids)

        if not is_batch:
            self.save(config)

    def clear_workflow_resolutions(self, name: str) -> bool:
        """Clear model resolutions for a workflow."""
        config = self.load()
        workflows = config.get('tool', {}).get('comfygit', {}).get('workflows', {})

        if name not in workflows:
            return False

        del workflows[name]
        # Clean up empty sections
        self.clean_empty_sections(config, 'tool', 'comfygit', 'workflows')
        self.save(config)
        logger.info(f"Cleared model resolutions for workflow: {name}")
        return True

    # === Per-workflow custom_node_map methods ===

    def get_custom_node_map(self, workflow_name: str, config: dict | None = None) -> dict[str, str | bool]:
        """Get custom_node_map for a specific workflow.

        Args:
            workflow_name: Name of workflow
            config: Optional in-memory config for batched reads. If None, loads from disk.

        Returns:
            Dict mapping node_type -> package_id (or false for optional)
        """
        try:
            if config is None:
                config = self.load()
            workflow_data = config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(workflow_name, {})
            return workflow_data.get('custom_node_map', {})
        except Exception:
            return {}

    def set_custom_node_mapping(self, workflow_name: str, node_type: str, package_id: str | None) -> None:
        """Set a single custom_node_map entry for a workflow (progressive write).

        Args:
            workflow_name: Name of workflow
            node_type: Node type to map
            package_id: Package ID (or None for optional = false)
        """
        config = self.load()
        workflow = self._ensure_workflow_entry(config, workflow_name)

        # Ensure custom_node_map exists
        if 'custom_node_map' not in workflow:
            workflow['custom_node_map'] = {}

        # Set mapping (false for optional, package_id string for resolved)
        if package_id is None:
            workflow['custom_node_map'][node_type] = False
        else:
            workflow['custom_node_map'][node_type] = package_id

        self.save(config)
        logger.debug(f"Set custom_node_map for workflow '{workflow_name}': {node_type} -> {package_id}")

    def remove_custom_node_mapping(self, workflow_name: str, node_type: str, config: dict | None = None) -> bool:
        """Remove a single custom_node_map entry for a workflow.

        Args:
            workflow_name: Name of workflow
            node_type: Node type to remove
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.

        Returns:
            True if removed, False if not found
        """
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflow_data = config.get('tool', {}).get('comfygit', {}).get('workflows', {}).get(workflow_name, {})

        if 'custom_node_map' not in workflow_data or node_type not in workflow_data['custom_node_map']:
            return False

        del workflow_data['custom_node_map'][node_type]

        # Clean up empty custom_node_map
        if not workflow_data['custom_node_map']:
            del workflow_data['custom_node_map']

        if not is_batch:
            self.save(config)

        logger.debug(f"Removed custom_node_map entry for workflow '{workflow_name}': {node_type}")
        return True

    def remove_workflows(self, workflow_names: list[str], config: dict | None = None) -> int:
        """Remove workflow sections from pyproject.toml.

        Args:
            workflow_names: List of workflow names to remove
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.

        Returns:
            Number of workflows removed
        """
        if not workflow_names:
            return 0

        is_batch = config is not None
        if not is_batch:
            config = self.load()

        workflows = config.get('tool', {}).get('comfygit', {}).get('workflows', {})

        removed_count = 0
        for name in workflow_names:
            if name in workflows:
                del workflows[name]
                removed_count += 1
                logger.debug(f"Removed workflow section: {name}")

        if removed_count > 0:
            # Clean up empty workflows section
            self.clean_empty_sections(config, 'tool', 'comfygit', 'workflows')
            if not is_batch:
                self.save(config)
            logger.info(f"Removed {removed_count} workflow section(s) from pyproject.toml")

        return removed_count

    def cleanup_node_references(self, node_identifier: str, node_name: str | None = None) -> int:
        """Remove references to a node from all workflow nodes lists.

        Called when a node is removed to clean up orphaned references in workflows.

        Args:
            node_identifier: Primary identifier (registry ID or package name)
            node_name: Optional alternate name to also remove (for case where
                       identifier differs from directory name)

        Returns:
            Number of workflows updated
        """
        config = self.load()
        workflows = config.get('tool', {}).get('comfygit', {}).get('workflows', {})

        if not workflows:
            return 0

        # Build set of identifiers to remove (case-insensitive matching)
        identifiers_to_remove = {node_identifier.lower()}
        if node_name and node_name.lower() != node_identifier.lower():
            identifiers_to_remove.add(node_name.lower())

        updated_count = 0
        for workflow_name, workflow_data in workflows.items():
            nodes_list = workflow_data.get('nodes', [])
            if not nodes_list:
                continue

            # Filter out removed node (case-insensitive)
            updated_nodes = [n for n in nodes_list if n.lower() not in identifiers_to_remove]

            if len(updated_nodes) != len(nodes_list):
                # Nodes were removed - update the workflow
                if updated_nodes:
                    workflow_data['nodes'] = sorted(updated_nodes)
                else:
                    # No nodes left - remove the key entirely
                    del workflow_data['nodes']
                updated_count += 1
                logger.debug(f"Removed node reference '{node_identifier}' from workflow '{workflow_name}'")

        if updated_count > 0:
            self.save(config)
            logger.info(f"Cleaned up node references from {updated_count} workflow(s)")

        return updated_count


class ModelHandler(BaseHandler):
    """Handles global model manifest in pyproject.toml.

    Note: This stores ONLY resolved models with hashes for deduplication.
    Unresolved models are stored per-workflow only.
    """

    def add_model(self, model: ManifestModel, config: dict | None = None) -> None:
        """Add a model to the global manifest.

        If model already exists, merges sources (union of old and new).

        Args:
            model: ManifestModel object with hash, filename, size, etc.
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.

        Raises:
            CDPyprojectError: If save fails
        """
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        # Ensure sections exist
        self.ensure_section(config, "tool", "comfygit", "models")

        # Check if model already exists and merge sources
        # In batch mode, check in-memory config instead of loading from disk
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})
        if model.hash in models_section:
            existing_dict = models_section[model.hash]
            existing_sources = existing_dict.get('sources', [])
            model.sources = list(set(existing_sources + model.sources))

        # Serialize to inline table for compact representation
        model_dict = model.to_toml_dict()
        model_entry = tomlkit.inline_table()
        for key, value in model_dict.items():
            model_entry[key] = value

        config["tool"]["comfygit"]["models"][model.hash] = model_entry

        if not is_batch:
            self.save(config)

        logger.debug(f"Added model: {model.filename} ({model.hash[:8]}...)")

    def get_all(self) -> list[ManifestModel]:
        """Get all models in manifest.

        Returns:
            List of ManifestModel objects
        """
        try:
            config = self.load()
            models_data = config.get("tool", {}).get("comfygit", {}).get("models", {})

            return [
                ManifestModel.from_toml_dict(hash_key, data)
                for hash_key, data in models_data.items()
            ]
        except Exception as e:
            logger.debug(f"Error loading models: {e}")
            return []

    def get_by_hash(self, model_hash: str) -> ManifestModel | None:
        """Get a specific model by hash.

        Args:
            model_hash: Model hash to look up

        Returns:
            ManifestModel if found, None otherwise
        """
        try:
            config = self.load()
            models_data = config.get("tool", {}).get("comfygit", {}).get("models", {})

            if model_hash in models_data:
                return ManifestModel.from_toml_dict(model_hash, models_data[model_hash])
            return None
        except Exception as e:
            logger.warning(f"Error getting model by hash {model_hash}: {e}")
            return None

    def remove_model(self, model_hash: str) -> bool:
        """Remove a model from the manifest.

        Args:
            model_hash: Model hash to remove

        Returns:
            True if removed, False if not found
        """
        config = self.load()
        models = config.get("tool", {}).get("comfygit", {}).get("models", {})

        if model_hash in models:
            del models[model_hash]
            self.save(config)
            logger.debug(f"Removed model: {model_hash[:8]}...")
            return True

        return False

    def get_all_model_hashes(self) -> set[str]:
        """Get all model hashes in manifest.

        Returns:
            Set of all model hashes
        """
        config = self.load()
        models = config.get("tool", {}).get("comfygit", {}).get("models", {})
        return set(models.keys())

    def cleanup_orphans(self, config: dict | None = None) -> None:
        """Remove models from global table that aren't referenced by any workflow.

        This should be called after all workflows have been processed to clean up
        models that were removed from all workflows.

        Args:
            config: Optional in-memory config for batched writes. If None, loads and saves immediately.
        """
        is_batch = config is not None
        if not is_batch:
            config = self.load()

        # Collect all model hashes referenced by ANY workflow
        # Read from in-memory config instead of loading from disk
        referenced_hashes = set()
        all_workflows = config.get('tool', {}).get('comfygit', {}).get('workflows', {})

        for _workflow_name, workflow_data in all_workflows.items():
            workflow_models_data = workflow_data.get('models', [])
            for model_data in workflow_models_data:
                # Only track resolved models (unresolved models aren't in global table)
                if model_data.get('hash') and model_data.get('status') == "resolved":
                    referenced_hashes.add(model_data['hash'])

        # Get all hashes in global models table (from in-memory config)
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})
        global_hashes = set(models_section.keys())

        # Remove orphans (in global but not referenced)
        orphaned_hashes = global_hashes - referenced_hashes

        if orphaned_hashes:
            for model_hash in orphaned_hashes:
                if model_hash in models_section:
                    del models_section[model_hash]
                    logger.debug(f"Removed orphaned model: {model_hash[:8]}...")

            if not is_batch:
                self.save(config)

            logger.info(f"Cleaned up {len(orphaned_hashes)} orphaned model(s)")
