"""Tests to verify workspace-relative caching behavior.

These tests verify that all caching is properly workspace-relative with no
environment variable bypasses or platform-specific fallbacks.
"""

import tempfile
from pathlib import Path

import pytest
from comfygit_core.caching.api_cache import APICacheManager
from comfygit_core.caching.base import CacheBase, ContentCacheBase
from comfygit_core.caching.comfyui_cache import ComfyUICacheManager
from comfygit_core.caching.custom_node_cache import CustomNodeCacheManager


class TestWorkspaceRelativeCaching:
    """Test that all caches are workspace-relative."""

    def test_cache_base_requires_path(self):
        """CacheBase should require explicit cache_base_path."""
        with pytest.raises(ValueError, match="cache_base_path is required"):
            CacheBase()

    def test_content_cache_base_requires_path(self):
        """ContentCacheBase should require explicit cache_base_path."""
        with pytest.raises(ValueError, match="cache_base_path is required"):
            ContentCacheBase(content_type="test")

    def test_api_cache_manager_requires_path(self):
        """APICacheManager should require explicit cache_base_path."""
        with pytest.raises(ValueError, match="cache_base_path is required"):
            APICacheManager()

    def test_custom_node_cache_manager_requires_path(self):
        """CustomNodeCacheManager should require explicit cache_base_path."""
        with pytest.raises(ValueError, match="cache_base_path is required"):
            CustomNodeCacheManager()

    def test_comfyui_cache_manager_requires_path(self):
        """ComfyUICacheManager should require explicit cache_base_path."""
        with pytest.raises(ValueError, match="cache_base_path is required"):
            ComfyUICacheManager()

    def test_cache_managers_use_provided_path(self):
        """All cache managers should use the provided workspace cache path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_cache = Path(tmpdir) / "comfygit_cache"
            workspace_cache.mkdir()

            # Create cache managers
            api_cache = APICacheManager(cache_base_path=workspace_cache)
            custom_node_cache = CustomNodeCacheManager(cache_base_path=workspace_cache)
            comfyui_cache = ComfyUICacheManager(cache_base_path=workspace_cache)

            # Verify they all use the workspace cache path
            assert str(workspace_cache) in str(api_cache.cache_dir)
            assert str(workspace_cache) in str(custom_node_cache.cache_dir)
            assert str(workspace_cache) in str(comfyui_cache.cache_dir)

    def test_multiple_workspaces_have_isolated_caches(self):
        """Multiple workspaces should have completely isolated caches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace1_cache = Path(tmpdir) / "workspace1" / "comfygit_cache"
            workspace2_cache = Path(tmpdir) / "workspace2" / "comfygit_cache"
            workspace1_cache.mkdir(parents=True)
            workspace2_cache.mkdir(parents=True)

            # Create caches for two different workspaces
            cache1 = APICacheManager(cache_base_path=workspace1_cache)
            cache2 = APICacheManager(cache_base_path=workspace2_cache)

            # Set a value in cache1
            cache1.set("test_type", "test_key", {"data": "value1"})

            # Cache2 should not have access to cache1's data
            result = cache2.get("test_type", "test_key")
            assert result is None

    def test_cache_directory_creation_fails_raises_error(self):
        """Cache should raise error if directory creation fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file where we want the cache directory
            invalid_path = Path(tmpdir) / "file_not_dir"
            invalid_path.write_text("blocking file")

            # Trying to create cache should raise error
            with pytest.raises(Exception):  # ComfyDockError
                APICacheManager(cache_base_path=invalid_path / "subdir")
