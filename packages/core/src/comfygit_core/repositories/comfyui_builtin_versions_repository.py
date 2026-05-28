"""Repository for version-indexed ComfyUI builtin nodes."""

from __future__ import annotations

import json
from functools import cached_property
from typing import TYPE_CHECKING

from ..logging.logging_config import get_logger
from ..models.comfyui_builtin_versions import (
    BuiltinVersionGateInfo,
    ComfyUIBuiltinVersions,
)

if TYPE_CHECKING:
    from ..services.registry_data_manager import RegistryDataManager

logger = get_logger(__name__)


class ComfyUIBuiltinVersionsRepository:
    """Loads and serves version-indexed ComfyUI builtin metadata."""

    def __init__(self, data_manager: RegistryDataManager):
        self.data_manager = data_manager
        self.builtins_path = data_manager.get_builtin_versions_path()

    @cached_property
    def database(self) -> ComfyUIBuiltinVersions | None:
        """Load builtins database from cache if available."""
        if not self.builtins_path.exists():
            logger.debug(
                "ComfyUI builtins-by-version file not available at %s",
                self.builtins_path
            )
            return None

        try:
            with open(self.builtins_path, encoding="utf-8") as f:
                data = json.load(f)
            return ComfyUIBuiltinVersions.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load ComfyUI builtins-by-version data: %s", e)
            return None
        except Exception as e:
            logger.warning("Unexpected error loading builtins-by-version data: %s", e)
            return None

    def clear_cached_data(self) -> None:
        """Clear in-memory builtin version data after the backing cache file changes."""
        self.__dict__.pop("database", None)

    def is_available(self) -> bool:
        """Return whether builtin version data is currently available."""
        return self.database is not None

    def is_known_builtin(self, node_type: str) -> bool:
        """Return True when node is known in any ComfyUI version."""
        if self.database is None:
            return False
        return self.database.is_known_builtin(node_type)

    def is_present_at_version(self, node_type: str, current_version: str | None) -> bool | None:
        """Return builtin presence at current version (None when unknown)."""
        if self.database is None:
            return None
        return self.database.is_present_at_version(node_type, current_version)

    def get_version_gate_info(
        self,
        node_type: str,
        current_version: str | None
    ) -> BuiltinVersionGateInfo | None:
        """Return version-gated details for a known builtin missing now."""
        if self.database is None:
            return None
        return self.database.get_version_gate_info(node_type, current_version)
