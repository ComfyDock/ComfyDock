"""Shared pyproject manifest handler primitives."""
from __future__ import annotations

from typing import TYPE_CHECKING

import tomlkit

if TYPE_CHECKING:
    from ..managers.pyproject_manager import PyprojectManager


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
