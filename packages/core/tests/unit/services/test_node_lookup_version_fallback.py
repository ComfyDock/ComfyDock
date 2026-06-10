"""Tests for NodeLookupService API-first with cache fallback behavior.

Tests for the scenario where:
1. API lookup succeeds → return API result
2. API lookup fails (network error) → fall back to local cache
3. Explicit git clone uses correct ref (tag vs commit)
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from comfygit_core.models.shared import NodeInfo
from comfygit_core.services.node_lookup_service import (
    GIT_NODE_DOWNLOAD_TIMEOUT_SECONDS,
    NodeLookupService,
)


class TestDownloadToCacheGitBehavior:
    """Test registry artifact and explicit git behavior in download_to_cache."""

    @pytest.fixture
    def cache_dir(self):
        """Create a temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_registry_node_without_artifact_does_not_fallback_to_git(self, cache_dir):
        """Registry installs without artifacts should fail instead of cloning git."""
        # ARRANGE
        node_info = NodeInfo(
            name="ComfyUI-AKatz-Nodes",
            registry_id="comfyui-akatz-nodes",
            repository="https://github.com/akatz-ai/comfyui-akatz-nodes",
            version="1.11.1",  # Semver, not a git tag
            download_url=None,
            source="registry"
        )

        service = NodeLookupService(cache_path=cache_dir)

        # Mock at the utils.git module level where it's imported from
        with patch('comfygit_core.utils.git.git_clone') as mock_git_clone:
            # ACT
            result = service.download_to_cache(node_info)

            # ASSERT
            assert result is None
            mock_git_clone.assert_not_called()

    def test_git_clone_uses_ref_when_version_is_git_tag(self, cache_dir):
        """SHOULD use ref when version looks like a valid git tag (v1.11.1).

        Git-style versions prefixed with 'v' should be used as refs.
        """
        # ARRANGE
        node_info = NodeInfo(
            name="Some-Node",
            repository="https://github.com/example/some-node",
            version="v1.11.1",  # Git-style tag
            download_url=None,
            source="git"
        )

        service = NodeLookupService(cache_path=cache_dir)

        with patch('comfygit_core.utils.git.git_clone') as mock_git_clone:
            # ACT
            service.download_to_cache(node_info)

            # ASSERT
            mock_git_clone.assert_called_once()
            call_kwargs = mock_git_clone.call_args
            # Should use git tag as ref
            assert call_kwargs.kwargs.get('ref') == "v1.11.1"

    def test_git_clone_uses_ref_when_version_is_commit_hash(self, cache_dir):
        """SHOULD use ref when version is a commit hash."""
        # ARRANGE
        node_info = NodeInfo(
            name="Some-Node",
            repository="https://github.com/example/some-node",
            version="abc123def456789012345678901234567890abcd",  # 40-char commit hash
            download_url=None,
            source="git"
        )

        service = NodeLookupService(cache_path=cache_dir)

        with patch('comfygit_core.utils.git.git_clone') as mock_git_clone:
            # ACT
            service.download_to_cache(node_info)

            # ASSERT
            mock_git_clone.assert_called_once()
            call_kwargs = mock_git_clone.call_args
            # Should use commit hash as ref
            assert call_kwargs.kwargs.get('ref') == "abc123def456789012345678901234567890abcd"
            assert call_kwargs.kwargs.get("timeout") == GIT_NODE_DOWNLOAD_TIMEOUT_SECONDS

    def test_git_clone_uses_extended_timeout_for_node_downloads(self, cache_dir):
        """Custom node repositories can be slow enough to exceed generic command timeouts."""
        node_info = NodeInfo(
            name="Slow-Node",
            repository="https://github.com/example/slow-node",
            version=None,
            download_url=None,
            source="git",
        )

        service = NodeLookupService(cache_path=cache_dir)

        with patch("comfygit_core.utils.git.git_clone") as mock_git_clone:
            service.download_to_cache(node_info)

            mock_git_clone.assert_called_once()
            assert mock_git_clone.call_args.kwargs.get("timeout") == GIT_NODE_DOWNLOAD_TIMEOUT_SECONDS
