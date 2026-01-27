"""Manages dynamic registry data fetching and caching."""
import json
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from ..constants import GITHUB_NODE_MAPPINGS_URL, MAX_REGISTRY_DATA_AGE_HOURS
from ..logging.logging_config import get_logger

logger = get_logger(__name__)


class RegistryDataManager:
    """Manages fetching and caching of registry node mappings."""

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
            if self._fetch_mappings():
                logger.info("Successfully fetched registry data")
            else:
                logger.error("Failed to fetch registry data - no mappings available")
                return self.mappings_file  # Return path even if doesn't exist

        # If file exists but is stale, try to update (non-blocking)
        elif self._is_stale():
            logger.debug("Registry data is stale, attempting refresh...")
            if self._fetch_mappings():
                logger.info("Updated registry data")
            else:
                logger.warning("Using stale registry data (update failed)")

        return self.mappings_file

    def _is_stale(self) -> bool:
        """Check if cached data is older than MAX_AGE_HOURS."""
        if not self.mappings_file.exists():
            return True

        age_seconds = time.time() - self.mappings_file.stat().st_mtime
        age_hours = age_seconds / 3600
        return age_hours > self.MAX_AGE_HOURS

    def _fetch_mappings(self) -> bool:
        """Fetch latest mappings from GitHub.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create request with timeout
            req = Request(GITHUB_NODE_MAPPINGS_URL, headers={
                'User-Agent': 'ComfyDock/1.0',
                'Accept': 'application/json'
            })

            # Download with timeout
            with urlopen(req, timeout=self.FETCH_TIMEOUT) as response:
                data = response.read()

            # Parse to validate JSON
            mappings = json.loads(data)

            # Write atomically (temp file + replace)
            # Note: replace() works cross-platform, rename() fails on Windows when target exists
            temp_file = self.mappings_file.with_suffix('.tmp')
            temp_file.write_bytes(data)
            temp_file.replace(self.mappings_file)

            # Update metadata
            self._write_metadata({
                'updated_at': time.time(),
                'version': mappings.get('version', 'unknown'),
                'stats': mappings.get('stats', {})
            })

            return True

        except (TimeoutError, URLError) as e:
            logger.debug(f"Network error fetching registry data: {e}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in registry response: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error fetching registry data: {e}")
            return False

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
            True if successful
        """
        logger.info("Force updating registry data...")
        return self._fetch_mappings()

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
            'version': None
        }

        if self.mappings_file.exists():
            age_seconds = time.time() - self.mappings_file.stat().st_mtime
            age_hours = age_seconds / 3600
            info['age_hours'] = round(age_hours, 1)
            info['stale'] = age_hours > self.MAX_AGE_HOURS

        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, encoding='utf-8') as f:
                    metadata = json.load(f)
                    info['version'] = metadata.get('version')
            except:
                pass

        return info
