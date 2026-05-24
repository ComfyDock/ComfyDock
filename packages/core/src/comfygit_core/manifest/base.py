"""Shared pyproject manifest handler primitives."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import tomlkit

from .store import PyprojectDocument

if TYPE_CHECKING:
    from ..managers.pyproject_manager import PyprojectManager


class BaseHandler:
    """Base handler providing common functionality."""

    def __init__(self, manager: PyprojectManager):
        self.manager = manager

    def load(self) -> dict[str, Any]:
        """Load a mutable pyproject document for handler implementation code.

        PyprojectManager.load() intentionally returns TOMLKit's TOMLDocument at
        the storage boundary. Section handlers operate inside the pyproject
        implementation layer, where nested TOMLKit tables behave like mutable
        mappings. Returning a typed mapping view here keeps Pylance/Pyright from
        leaking TOMLKit's broad Item union into every table mutation.
        """
        return cast(dict[str, Any], self.manager.load())

    def save(self, config: dict[str, Any] | PyprojectDocument) -> None:
        """Save configuration through manager.

        Raises:
            CDPyprojectError
        """
        self.manager.save(config)

    def ensure_section(self, config: dict[str, Any], *path: str) -> dict[str, Any]:
        """Ensure a nested section exists in config."""
        current: dict[str, Any] = config
        for key in path:
            if key not in current:
                current[key] = tomlkit.table()
            current = cast(dict[str, Any], current[key])
        return current

    def clean_empty_sections(self, config: dict[str, Any], *path: str) -> None:
        """Clean up empty sections by removing them from bottom up."""
        if not path:
            return

        # Navigate to parent of the last key
        current: dict[str, Any] = config
        for key in path[:-1]:
            if key not in current:
                return
            current = cast(dict[str, Any], current[key])

        # Check if the final key exists and is empty
        final_key = path[-1]
        if final_key in current and not current[final_key]:
            del current[final_key]
            # Recursively clean parent if it becomes empty (except top-level sections)
            if len(path) > 2 and not current:
                self.clean_empty_sections(config, *path[:-1])
