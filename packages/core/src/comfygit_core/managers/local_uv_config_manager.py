"""Manages .local-uv-config file for machine-specific UV configuration."""
from __future__ import annotations

from pathlib import Path

import tomlkit
from tomlkit.exceptions import TOMLKitError

from ..logging.logging_config import get_logger

logger = get_logger(__name__)


class LocalUVConfigManager:
    """Manage machine-specific UV config overrides stored in .local-uv-config."""

    def __init__(self, cec_path: Path):
        """Initialize manager.

        Args:
            cec_path: Path to the .cec directory
        """
        self.cec_path = cec_path
        self.config_path = cec_path / ".local-uv-config"

    def exists(self) -> bool:
        """Return True if .local-uv-config exists."""
        return self.config_path.exists()

    def load(self) -> dict:
        """Load .local-uv-config TOML file.

        Returns:
            Parsed TOML dict (empty if file missing or empty)
        """
        if not self.exists():
            return {}

        try:
            with open(self.config_path, encoding="utf-8") as f:
                config = tomlkit.load(f)
        except (OSError, TOMLKitError) as exc:
            raise ValueError(f"Failed to parse {self.config_path}: {exc}") from exc

        return config or {}

    def has_config(self) -> bool:
        """Return True if the file exists and has any config."""
        return bool(self.load())

    def get_uv_config(self) -> dict:
        """Return UV config payload for injection.

        Expected file format (top-level):
            [sources]
            pkg = { path = "/abs/path", editable = true }

            [[index]]
            name = "corp"
            url = "https://pypi.corp/simple/"

        Returns dict with:
            - indexes: list of index tables
            - sources: dict of package sources
            - constraints: list of constraint dependencies (optional)
        """
        if not self.exists():
            return {}

        config = self.load()
        if not config:
            return {}

        # Ensure this machine-specific file is gitignored
        self.ensure_gitignore_entry()

        sources = config.get("sources", {})
        indexes = config.get("index", [])
        constraints = config.get("constraint-dependencies", []) or config.get("constraints", [])

        if indexes and not isinstance(indexes, list):
            indexes = [indexes]

        return {
            "indexes": indexes,
            "sources": sources,
            "constraints": constraints,
        }

    def ensure_gitignore_entry(self) -> None:
        """Ensure .local-uv-config is in .gitignore."""
        gitignore_path = self.cec_path / ".gitignore"
        entry = ".local-uv-config"

        if not gitignore_path.exists():
            gitignore_path.write_text(f"# Local UV config (machine-specific)\n{entry}\n")
            logger.debug(f"Created .gitignore with entry: {entry}")
            return

        current_content = gitignore_path.read_text()
        for line in current_content.split("\n"):
            stripped = line.split("#")[0].strip()
            if stripped == entry:
                return

        if not current_content.endswith("\n"):
            current_content += "\n"
        current_content += f"\n# Local UV config (machine-specific)\n{entry}\n"
        gitignore_path.write_text(current_content)
        logger.info(f"Added {entry} to .gitignore")
