"""Manages dynamic registry data fetching and caching."""
import json
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from ..constants import (
    GITHUB_COMFYUI_BUILTINS_BY_VERSION_URL,
    GITHUB_NODE_MAPPINGS_URL,
    MAX_REGISTRY_DATA_AGE_HOURS,
)
from ..logging.logging_config import get_logger

logger = get_logger(__name__)


class RegistryDataManager:
    """Manages fetching and caching of registry node mappings and metadata."""

    MAX_AGE_HOURS = MAX_REGISTRY_DATA_AGE_HOURS
    FETCH_TIMEOUT = 10  # seconds

    def __init__(self, cache_dir: Path):
        """Initialize with cache directory.

        Args:
            cache_dir: Directory to store cached registry data
        """
        self.cache_dir = cache_dir
        self.registry_dir = cache_dir / "registry"
        self.custom_nodes_dir = cache_dir / "custom_nodes"
        self.mappings_file = self.custom_nodes_dir / "node_mappings.json"
        self.builtin_versions_file = self.custom_nodes_dir / "comfyui_builtins_by_version.json"
        self.metadata_file = self.registry_dir / "metadata.json"

        # Ensure directories exist
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.custom_nodes_dir.mkdir(parents=True, exist_ok=True)

    def get_mappings_path(self) -> Path:
        """Get path to node mappings file, fetching if needed.

        Returns:
            Path to node_mappings.json (may be stale if fetch fails)
        """
        # If no file exists, we MUST fetch
        if not self.mappings_file.exists():
            logger.info("No cached registry data found, fetching...")
            mappings_ok, _builtins_ok = self._fetch_registry_data(
                fetch_mappings=True,
                fetch_builtin_versions=True
            )
            if mappings_ok:
                logger.info("Successfully fetched registry data")
            else:
                logger.error("Failed to fetch registry data - no mappings available")
                return self.mappings_file  # Return path even if doesn't exist

        # If file exists but is stale, try to update (non-blocking)
        elif self._is_stale(self.mappings_file):
            logger.debug("Registry data is stale, attempting refresh...")
            mappings_ok, _builtins_ok = self._fetch_registry_data(
                fetch_mappings=True,
                fetch_builtin_versions=True
            )
            if mappings_ok:
                logger.info("Updated registry data")
            else:
                logger.warning("Using stale registry data (update failed)")

        return self.mappings_file

    def get_builtin_versions_path(self) -> Path:
        """Get path to ComfyUI builtins-by-version file.

        Returns:
            Path to comfyui_builtins_by_version.json (may be missing if fetch fails)
        """
        if not self.builtin_versions_file.exists():
            logger.debug("No cached ComfyUI builtins-by-version data found, fetching...")
            if self._fetch_builtin_versions():
                logger.info("Fetched ComfyUI builtins-by-version data")
            else:
                logger.warning("Could not fetch ComfyUI builtins-by-version data")

        elif self._is_stale(self.builtin_versions_file):
            logger.debug("ComfyUI builtins-by-version data is stale, attempting refresh...")
            if self._fetch_builtin_versions():
                logger.info("Updated ComfyUI builtins-by-version data")
            else:
                logger.warning("Using stale ComfyUI builtins-by-version data (update failed)")

        return self.builtin_versions_file

    def _is_stale(self, target_file: Path) -> bool:
        """Check if cached data file is older than MAX_AGE_HOURS."""
        if not target_file.exists():
            return True

        age_seconds = time.time() - target_file.stat().st_mtime
        age_hours = age_seconds / 3600
        return age_hours > self.MAX_AGE_HOURS

    def _fetch_registry_data(
        self,
        fetch_mappings: bool = True,
        fetch_builtin_versions: bool = True
    ) -> tuple[bool, bool]:
        """Fetch one or both registry data files.

        Returns:
            Tuple of (mappings_success, builtin_versions_success)
        """
        mappings_ok = True
        builtins_ok = True

        if fetch_mappings:
            mappings_ok = self._fetch_mappings()
        if fetch_builtin_versions:
            builtins_ok = self._fetch_builtin_versions()

        return mappings_ok, builtins_ok

    def _fetch_json_file(self, url: str, target_file: Path) -> dict | None:
        """Fetch JSON from URL and write to target path atomically.

        Returns:
            Parsed JSON dict on success, None on failure.
        """
        try:
            req = Request(url, headers={
                'User-Agent': 'ComfyGit/1.0',
                'Accept': 'application/json'
            })
            with urlopen(req, timeout=self.FETCH_TIMEOUT) as response:
                data = response.read()

            parsed = json.loads(data)

            temp_file = target_file.with_suffix('.tmp')
            temp_file.write_bytes(data)
            temp_file.replace(target_file)

            return parsed

        except (TimeoutError, URLError) as e:
            logger.debug(f"Network error fetching registry data from {url}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in registry response from {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching registry data from {url}: {e}")
            return None

    def _fetch_mappings(self) -> bool:
        """Fetch latest node mappings from GitHub.

        Returns:
            True if successful, False otherwise
        """
        mappings = self._fetch_json_file(GITHUB_NODE_MAPPINGS_URL, self.mappings_file)
        if mappings is None:
            return False

        # Keep legacy top-level metadata keys for compatibility.
        self._update_metadata_section("node_mappings", {
            'updated_at': time.time(),
            'version': mappings.get('version', 'unknown'),
            'stats': mappings.get('stats', {})
        })
        return True

    def _fetch_builtin_versions(self) -> bool:
        """Fetch latest ComfyUI builtins-by-version data from GitHub.

        Returns:
            True if successful, False otherwise.
        """
        builtins = self._fetch_json_file(
            GITHUB_COMFYUI_BUILTINS_BY_VERSION_URL,
            self.builtin_versions_file
        )
        if builtins is None:
            return False

        self._update_metadata_section("builtin_versions", {
            'updated_at': time.time(),
            'version': builtins.get('version', 'unknown'),
            'stats': builtins.get('stats', {})
        })
        return True

    def _read_metadata(self) -> dict:
        """Read metadata file if present, otherwise return empty dict."""
        if not self.metadata_file.exists():
            return {}
        try:
            with open(self.metadata_file, encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _update_metadata_section(self, section: str, payload: dict) -> None:
        """Merge/update metadata section while preserving existing keys."""
        metadata = self._read_metadata()
        metadata[section] = payload

        # Preserve legacy top-level mapping metadata keys for callers.
        if section == "node_mappings":
            metadata['updated_at'] = payload.get('updated_at')
            metadata['version'] = payload.get('version')
            metadata['stats'] = payload.get('stats')

        self._write_metadata(metadata)

    def _write_metadata(self, metadata: dict) -> None:
        """Write metadata about the cached data."""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to write metadata: {e}")

    def force_update(self) -> bool:
        """Force fetch latest mappings.

        Returns:
            True if node mappings fetch succeeds.
        """
        logger.info("Force updating registry data...")
        mappings_ok, builtins_ok = self._fetch_registry_data(
            fetch_mappings=True,
            fetch_builtin_versions=True
        )
        if not builtins_ok:
            logger.warning("Builtins-by-version update failed (non-fatal)")
        return mappings_ok

    def get_cache_info(self) -> dict:
        """Get information about cached data.

        Returns:
            Dict with cache status and metadata
        """
        info = {
            'exists': self.mappings_file.exists(),
            'path': str(self.mappings_file),
            'stale': False,
            'age_hours': None,
            'version': None,
            'builtins_exists': self.builtin_versions_file.exists(),
            'builtins_path': str(self.builtin_versions_file),
            'builtins_stale': False,
            'builtins_age_hours': None,
            'builtins_version': None,
        }

        if self.mappings_file.exists():
            age_seconds = time.time() - self.mappings_file.stat().st_mtime
            age_hours = age_seconds / 3600
            info['age_hours'] = round(age_hours, 1)
            info['stale'] = age_hours > self.MAX_AGE_HOURS

        if self.builtin_versions_file.exists():
            age_seconds = time.time() - self.builtin_versions_file.stat().st_mtime
            age_hours = age_seconds / 3600
            info['builtins_age_hours'] = round(age_hours, 1)
            info['builtins_stale'] = age_hours > self.MAX_AGE_HOURS

        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, encoding='utf-8') as f:
                    metadata = json.load(f)
                    info['version'] = metadata.get('version')
                    builtins_meta = metadata.get('builtin_versions', {})
                    if isinstance(builtins_meta, dict):
                        info['builtins_version'] = builtins_meta.get('version')
            except Exception:
                pass

        return info
