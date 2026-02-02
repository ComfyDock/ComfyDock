"""Unified cache manager for API responses with expiration support."""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..logging.logging_config import get_logger
from ..models.exceptions import ComfyDockError

logger = get_logger(__name__)


class APICacheManager:
    """Manages persistent caching of API responses with expiration."""

    def __init__(self, cache_name: str = "api",
                 default_ttl_hours: int = 24,
                 cache_base_path: Path | None = None):
        """Initialize cache manager.

        Args:
            cache_name: Name of the cache subdirectory
            default_ttl_hours: Default time-to-live in hours for cache entries
            cache_base_path: Required cache base path (workspace cache directory)

        Raises:
            ValueError: If cache_base_path is None
        """
        if cache_base_path is None:
            raise ValueError(
                "cache_base_path is required. All caches must be workspace-relative."
            )
        self.cache_name = cache_name
        self.default_ttl_seconds = default_ttl_hours * 3600
        self.cache_dir = cache_base_path / cache_name
        self._ensure_cache_directory()

        logger.debug(f"Initialized API cache at: {self.cache_dir}")

    def _ensure_cache_directory(self):
        """Ensure cache directory exists.

        Raises:
            ComfyDockError: If cache directory creation fails
        """
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Cache directory: {self.cache_dir}")
        except Exception as e:
            raise ComfyDockError(
                f"Failed to create cache directory {self.cache_dir}. "
                f"Workspace cache should exist before cache initialization: {e}"
            )

    def _get_cache_file_path(self, cache_type: str) -> Path:
        """Get path for a specific cache file."""
        return self.cache_dir / f"{cache_type}_cache.json"

    def _sanitize_key(self, key: str) -> str:
        """Sanitize cache key to be filesystem-safe."""
        # Create a hash of the key to avoid filesystem issues
        key_hash = hashlib.md5(key.encode()).hexdigest()[:8]
        # Keep some readable part of the key
        safe_key = "".join(c if c.isalnum() or c in '-_' else '_' for c in key)
        return f"{safe_key[:50]}_{key_hash}"

    def get(self, cache_type: str, key: str, ttl_seconds: int | None = None) -> Any | None:
        """Get a value from cache if it exists and hasn't expired.

        Args:
            cache_type: Type of cache (e.g., 'github', 'registry')
            key: Cache key
            ttl_seconds: Time-to-live in seconds (overrides default)

        Returns:
            Cached value if valid, None if expired or not found
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        cache_file = self._get_cache_file_path(cache_type)

        if not cache_file.exists():
            return None

        try:
            logger.debug(f"Reading cache for {cache_type}:{key}")
            with open(cache_file, encoding='utf-8') as f:
                cache_data = json.load(f)

            logger.debug(f"Found {len(cache_data)} entries in cache for {cache_type}")
            sanitized_key = self._sanitize_key(key)
            if sanitized_key not in cache_data:
                logger.debug(f"Cache miss for {cache_type}:{key}")
                return None

            entry = cache_data[sanitized_key]
            timestamp = entry.get('timestamp', 0)

            logger.debug(f"Cache timestamp for {cache_type}:{key}: {timestamp}")

            # Check if entry has expired
            if time.time() - timestamp > ttl:
                logger.debug(f"Cache expired for {cache_type}:{key}")
                return None

            logger.debug(f"Cache hit for {cache_type}:{key}")
            return entry.get('data')

        except Exception as e:
            logger.warning(f"Error reading cache for {cache_type}: {e}")
            return None

    def set(self, cache_type: str, key: str, value: Any) -> bool:
        """Store a value in cache with current timestamp.

        Args:
            cache_type: Type of cache (e.g., 'github', 'registry')
            key: Cache key
            value: Value to cache

        Returns:
            True if successfully cached, False otherwise
        """
        cache_file = self._get_cache_file_path(cache_type)

        try:
            # Load existing cache
            if cache_file.exists():
                with open(cache_file, encoding='utf-8') as f:
                    cache_data = json.load(f)
            else:
                cache_data = {}

            # Add new entry
            sanitized_key = self._sanitize_key(key)
            cache_data[sanitized_key] = {
                'timestamp': time.time(),
                'data': value,
                'original_key': key  # Store original key for debugging
            }

            # Write updated cache
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)

            logger.debug(f"Cached {cache_type}:{key}")
            return True

        except Exception as e:
            logger.warning(f"Error writing cache for {cache_type}: {e}")
            return False

    def clear(self, cache_type: str | None = None):
        """Clear cache entries.

        Args:
            cache_type: Specific cache type to clear, or None to clear all
        """
        try:
            if cache_type:
                cache_file = self._get_cache_file_path(cache_type)
                if cache_file.exists():
                    cache_file.unlink()
                    logger.info(f"Cleared {cache_type} cache")
            else:
                # Clear all cache files
                for cache_file in self.cache_dir.glob("*_cache.json"):
                    cache_file.unlink()
                logger.info("Cleared all caches")
        except Exception as e:
            logger.warning(f"Error clearing cache: {e}")

    def cleanup_expired(self, cache_type: str | None = None):
        """Remove expired entries from cache.

        Args:
            cache_type: Specific cache type to clean, or None to clean all
        """
        cache_types = [cache_type] if cache_type else ['github', 'registry']

        for ct in cache_types:
            cache_file = self._get_cache_file_path(ct)
            if not cache_file.exists():
                continue

            try:
                with open(cache_file, encoding='utf-8') as f:
                    cache_data = json.load(f)

                # Filter out expired entries
                current_time = time.time()
                cleaned_data = {}
                expired_count = 0

                for key, entry in cache_data.items():
                    timestamp = entry.get('timestamp', 0)
                    if current_time - timestamp <= self.default_ttl_seconds:
                        cleaned_data[key] = entry
                    else:
                        expired_count += 1

                if expired_count > 0:
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(cleaned_data, f, indent=2)
                    logger.info(f"Removed {expired_count} expired entries from {ct} cache")

            except Exception as e:
                logger.warning(f"Error cleaning up {ct} cache: {e}")

