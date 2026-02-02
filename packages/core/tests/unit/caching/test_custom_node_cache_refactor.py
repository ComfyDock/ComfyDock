"""Tests for CustomNodeCacheManager extending ContentCacheBase.

These tests verify that CustomNodeCacheManager properly extends ContentCacheBase
after refactoring to eliminate code duplication.
"""


import pytest
from comfygit_core.caching.base import ContentCacheBase
from comfygit_core.caching.custom_node_cache import CustomNodeCacheManager
from comfygit_core.models.shared import NodeInfo


@pytest.fixture
def temp_cache(tmp_path):
    """Temporary cache for testing."""
    return tmp_path / "test_cache"


@pytest.fixture
def sample_node_info():
    """Sample node info for testing."""
    return NodeInfo(
        name="test-node",
        source="git",
        download_url="https://github.com/user/test-node.git",
        repository="https://github.com/user/test-node",
        version="main"
    )


def test_custom_node_cache_extends_content_base(temp_cache):
    """SHOULD be instance of ContentCacheBase after refactor."""
    cache = CustomNodeCacheManager(cache_base_path=temp_cache)
    assert isinstance(cache, ContentCacheBase), "CustomNodeCacheManager should extend ContentCacheBase"


def test_maintains_generate_cache_key_method(temp_cache, sample_node_info):
    """SHOULD maintain node-specific cache key generation."""
    cache = CustomNodeCacheManager(cache_base_path=temp_cache)

    # Should have generate_cache_key method
    assert hasattr(cache, 'generate_cache_key'), "Should have generate_cache_key method"

    # Should generate consistent keys
    key1 = cache.generate_cache_key(sample_node_info)
    key2 = cache.generate_cache_key(sample_node_info)
    assert key1 == key2, "Should generate consistent cache keys"
    assert isinstance(key1, str), "Cache key should be a string"
    assert len(key1) == 16, "Cache key should be 16 characters (truncated SHA256)"


def test_maintains_copy_from_cache_method(temp_cache, sample_node_info, tmp_path):
    """SHOULD maintain node-specific copy_from_cache with flattening logic."""
    cache = CustomNodeCacheManager(cache_base_path=temp_cache)

    # Should have copy_from_cache method
    assert hasattr(cache, 'copy_from_cache'), "Should have copy_from_cache method"

    # Create a cached node with versioned directory structure
    source_path = tmp_path / "source"
    versioned_dir = source_path / "test-node-1.0.0"
    versioned_dir.mkdir(parents=True)
    (versioned_dir / "test_file.py").write_text("# test")

    # Cache the node
    cache.cache_node(sample_node_info, source_path)

    # Copy from cache - should flatten the versioned directory
    dest_path = tmp_path / "dest" / "test-node"
    result = cache.copy_from_cache(sample_node_info, dest_path)

    assert result is True, "Should successfully copy from cache"
    assert dest_path.exists(), "Destination should exist"


def test_maintains_backward_compatibility_with_cache_node(temp_cache, sample_node_info, tmp_path):
    """SHOULD maintain backward compatible cache_node API."""
    cache = CustomNodeCacheManager(cache_base_path=temp_cache)

    # Create source directory with content
    source_path = tmp_path / "node_source"
    source_path.mkdir()
    (source_path / "test_file.py").write_text("# test content")

    # Should support cache_node method with same signature
    cached_path = cache.cache_node(sample_node_info, source_path)

    assert cached_path.exists(), "Should return existing cache path"
    assert (cached_path / "test_file.py").exists(), "Should cache the file content"

    # Should update index
    assert cache.is_cached(sample_node_info), "Should mark node as cached"


def test_uses_base_class_for_common_operations(temp_cache):
    """SHOULD use base class methods for common cache operations."""
    cache = CustomNodeCacheManager(cache_base_path=temp_cache)

    # Should have inherited properties from ContentCacheBase
    assert hasattr(cache, 'cache_base'), "Should inherit cache_base from base"
    assert hasattr(cache, 'store_dir'), "Should inherit store_dir from base"
    assert hasattr(cache, 'index_file'), "Should inherit index_file from base"
    assert hasattr(cache, 'index'), "Should inherit index from base"

    # Should have base methods available
    assert hasattr(cache, '_save_index'), "Should inherit _save_index from base"
    assert hasattr(cache, '_load_index'), "Should inherit _load_index from base"
    assert hasattr(cache, '_calculate_content_hash'), "Should inherit _calculate_content_hash from base"


def test_maintains_list_cached_nodes(temp_cache, sample_node_info, tmp_path):
    """SHOULD maintain list_cached_nodes method."""
    cache = CustomNodeCacheManager(cache_base_path=temp_cache)

    # Initially empty
    cached_nodes = cache.list_cached_nodes()
    assert isinstance(cached_nodes, list), "Should return a list"
    assert len(cached_nodes) == 0, "Should start empty"

    # After caching
    source_path = tmp_path / "node_source"
    source_path.mkdir()
    (source_path / "test.py").write_text("# test")
    cache.cache_node(sample_node_info, source_path)

    cached_nodes = cache.list_cached_nodes()
    assert len(cached_nodes) > 0, "Should have cached nodes"
