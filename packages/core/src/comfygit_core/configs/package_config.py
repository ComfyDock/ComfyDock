"""Package configuration for substitutions and exclusions."""

from pathlib import Path

import tomlkit

from ..logging.logging_config import get_logger

logger = get_logger(__name__)

# Default package substitutions - maps package to its preferred alternative
# When a node requests the key package, we install the value instead
DEFAULT_PACKAGE_SUBSTITUTIONS = {
    "opencv-python": "opencv-contrib-python-headless",
    "opencv-contrib-python": "opencv-contrib-python-headless",
    "opencv-python-headless": "opencv-contrib-python-headless",
}

# Default packages to exclude from installation
DEFAULT_EXCLUDE_PACKAGES = [
    "opencv-python",
    "opencv-contrib-python",
    "opencv-python-headless",
]

class PackageConfigManager:
    """Manages package_config.toml for an environment."""

    CONFIG_FILENAME = "package_config.toml"

    def __init__(self, cec_path: Path):
        self.cec_path = cec_path
        self.config_path = cec_path / self.CONFIG_FILENAME
        self._config: dict | None = None
        self._cache_mtime: float | None = None

    def load(self) -> dict:
        """Load config from file or return defaults (with mtime-based cache)."""
        if self.config_path.exists():
            current_mtime = self.config_path.stat().st_mtime
            if self._config is not None and self._cache_mtime == current_mtime:
                return self._config  # Cache hit

            with open(self.config_path, encoding="utf-8") as f:
                self._config = tomlkit.load(f)
            self._cache_mtime = current_mtime
        else:
            if self._config is None:
                self._config = self._create_default_config()

        return self._config

    def save(self, config: dict | None = None) -> None:
        """Save config to file."""
        if config is not None:
            self._config = config
        if self._config is None:
            self._config = self._create_default_config()

        with open(self.config_path, "w", encoding="utf-8") as f:
            tomlkit.dump(self._config, f)

        # Invalidate cache to ensure fresh reads pick up new mtime
        self._cache_mtime = None
        logger.debug(f"Saved package config to {self.config_path}")

    def ensure_exists(self) -> None:
        """Create config file with defaults if it doesn't exist."""
        if not self.config_path.exists():
            self.save(self._create_default_config())
            logger.info(f"Created default package config at {self.config_path}")

    def _create_default_config(self) -> dict:
        """Create default configuration."""
        doc = tomlkit.document()
        doc.add(tomlkit.comment("Package configuration for ComfyGit environment"))
        doc.add(tomlkit.comment("This file is git-tracked and can be customized per environment"))
        doc.add(tomlkit.nl())

        # Substitutions section
        doc.add(tomlkit.comment("Package substitutions - when a node requests the key, install the value instead"))
        subs = tomlkit.table()
        for k, v in DEFAULT_PACKAGE_SUBSTITUTIONS.items():
            subs[k] = v
        doc["substitutions"] = subs

        doc.add(tomlkit.nl())

        # Exclusions section
        doc.add(tomlkit.comment("Packages to exclude - these will NEVER be installed"))
        doc.add(tomlkit.comment("Use with substitutions to prevent conflicting packages"))
        exclude = tomlkit.table()
        exclude["packages"] = list(DEFAULT_EXCLUDE_PACKAGES)
        doc["exclude"] = exclude

        return doc

    @property
    def substitutions(self) -> dict[str, str]:
        """Get package substitution mappings."""
        config = self.load()
        return dict(config.get("substitutions", {}))

    @property
    def exclude_packages(self) -> list[str]:
        """Get list of packages to exclude."""
        config = self.load()
        return list(config.get("exclude", {}).get("packages", []))

    def apply_substitution(self, package: str) -> str:
        """Apply substitution to a package name if applicable.

        Args:
            package: Package name or requirement string (e.g., "opencv-python>=4.0")

        Returns:
            Substituted package name/requirement, or original if no substitution
        """
        from ..utils.dependency_parser import parse_dependency_string

        pkg_name, version_spec = parse_dependency_string(package)
        subs = self.substitutions

        if pkg_name.lower() in {k.lower() for k in subs}:
            # Find the actual key (case-insensitive match)
            for key, replacement in subs.items():
                if key.lower() == pkg_name.lower():
                    if version_spec:
                        result = f"{replacement}{version_spec}"
                    else:
                        result = replacement
                    logger.debug(f"Package substitution: {package} -> {result}")
                    return result

        return package
