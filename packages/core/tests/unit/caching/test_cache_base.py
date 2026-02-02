"""Unit tests for cache base classes (CacheBase and ContentCacheBase).

TDD tests to verify:
1. CacheBase requires workspace-relative cache paths
2. ContentCacheBase provides content caching infrastructure
"""

import tempfile
from pathlib import Path

import pytest
from comfygit_core.caching.base import CacheBase, ContentCacheBase


class TestCacheBase:
    """Test CacheBase workspace-relative path management."""

    def test_requires_explicit_cache_path(self):
        """SHOULD raise ValueError when cache_base_path is not provided."""
        with pytest.raises(ValueError, match="cache_base_path is required"):
            CacheBase(cache_name="comfygit")

    def test_explicit_cache_path(self):
        """SHOULD use explicit cache_base_path when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = Path(tmpdir) / "custom_cache"
            cache = CacheBase(cache_name="comfygit", cache_base_path=custom_path)

            assert cache.cache_base == custom_path

    def test_ensure_cache_dirs_creates_directories(self):
        """SHOULD create cache subdirectories when requested."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = CacheBase(cache_name="test", cache_base_path=Path(tmpdir))
            cache._ensure_cache_dirs("subdir1", "subdir2/nested")

            assert (cache.cache_base / "subdir1").exists()
            assert (cache.cache_base / "subdir2" / "nested").exists()


class TestContentCacheBase:
    """Test ContentCacheBase content caching infrastructure."""

    def test_initialization_creates_directory_structure(self):
        """SHOULD create content_type/store directories and index.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            assert cache.cache_dir.exists()
            assert cache.store_dir.exists()
            assert cache.cache_dir == Path(tmpdir) / "test_content"
            assert cache.store_dir == Path(tmpdir) / "test_content" / "store"

    def test_empty_index_on_first_load(self):
        """SHOULD have empty index when no index.json exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            assert cache.index == {}

    def test_save_and_load_index(self):
        """SHOULD persist and reload index correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and save
            cache1 = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )
            cache1.index["key1"] = {"data": "value1"}
            cache1._save_index()

            # Reload
            cache2 = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            assert cache2.index == {"key1": {"data": "value1"}}
            assert (Path(tmpdir) / "test_content" / "index.json").exists()

    def test_cache_content_creates_directory_structure(self):
        """SHOULD create cache_key/content directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            # Create source content
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            (source_dir / "file1.txt").write_text("content1")
            (source_dir / "subdir").mkdir()
            (source_dir / "subdir" / "file2.txt").write_text("content2")

            # Cache it
            cached_path = cache.cache_content(
                cache_key="test_key",
                source_path=source_dir,
                metadata={"version": "1.0.0"}
            )

            # Verify structure
            assert cached_path == cache.store_dir / "test_key" / "content"
            assert cached_path.exists()
            assert (cached_path / "file1.txt").read_text() == "content1"
            assert (cached_path / "subdir" / "file2.txt").read_text() == "content2"

    def test_cache_content_stores_metadata(self):
        """SHOULD store metadata.json with size, hash, and custom fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            (source_dir / "file.txt").write_text("test content")

            cache.cache_content(
                cache_key="test_key",
                source_path=source_dir,
                metadata={"custom_field": "custom_value"}
            )

            metadata_file = cache.store_dir / "test_key" / "metadata.json"
            assert metadata_file.exists()

            import json
            metadata = json.loads(metadata_file.read_text())
            assert metadata["cache_key"] == "test_key"
            assert "cached_at" in metadata
            assert "size_bytes" in metadata
            assert "content_hash" in metadata
            assert metadata["custom_field"] == "custom_value"

    def test_cache_content_updates_index(self):
        """SHOULD update index with cached item metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            (source_dir / "file.txt").write_text("test")

            cache.cache_content(
                cache_key="test_key",
                source_path=source_dir
            )

            assert "test_key" in cache.index
            assert cache.index["test_key"]["cache_key"] == "test_key"

    def test_cache_content_replaces_existing(self):
        """SHOULD replace existing cache entry when caching again."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            (source_dir / "file.txt").write_text("version1")

            # Cache first time
            cache.cache_content(cache_key="test_key", source_path=source_dir)

            # Change source
            (source_dir / "file.txt").write_text("version2")

            # Cache again
            cached_path = cache.cache_content(cache_key="test_key", source_path=source_dir)

            # Should have new content
            assert (cached_path / "file.txt").read_text() == "version2"

    def test_get_cached_path_returns_none_when_missing(self):
        """SHOULD return None when cache key doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            result = cache.get_cached_path("nonexistent_key")
            assert result is None

    def test_get_cached_path_returns_content_path(self):
        """SHOULD return content path when cache exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            (source_dir / "file.txt").write_text("test")

            cache.cache_content(cache_key="test_key", source_path=source_dir)

            cached_path = cache.get_cached_path("test_key")
            assert cached_path is not None
            assert cached_path.exists()
            assert (cached_path / "file.txt").exists()

    def test_calculate_content_hash_deterministic(self):
        """SHOULD produce same hash for identical content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            # Create identical directories
            dir1 = Path(tmpdir) / "dir1"
            dir1.mkdir()
            (dir1 / "file.txt").write_text("content")

            dir2 = Path(tmpdir) / "dir2"
            dir2.mkdir()
            (dir2 / "file.txt").write_text("content")

            hash1 = cache._calculate_content_hash(dir1)
            hash2 = cache._calculate_content_hash(dir2)

            assert hash1 == hash2

    def test_calculate_content_hash_different_for_different_content(self):
        """SHOULD produce different hashes for different content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ContentCacheBase(
                content_type="test_content",
                cache_base_path=Path(tmpdir)
            )

            dir1 = Path(tmpdir) / "dir1"
            dir1.mkdir()
            (dir1 / "file.txt").write_text("content1")

            dir2 = Path(tmpdir) / "dir2"
            dir2.mkdir()
            (dir2 / "file.txt").write_text("content2")

            hash1 = cache._calculate_content_hash(dir1)
            hash2 = cache._calculate_content_hash(dir2)

            assert hash1 != hash2


class ConcreteContentCache(ContentCacheBase):
    """Concrete implementation for testing abstract base."""

    def __init__(self, cache_base_path: Path | None = None):
        super().__init__("test_content", cache_base_path)
