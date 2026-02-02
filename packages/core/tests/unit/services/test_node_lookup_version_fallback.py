"""Tests for NodeLookupService API-first with cache fallback behavior.

Tests for the scenario where:
1. API lookup succeeds → return API result
2. API lookup fails (network error) → fall back to local cache
3. Git clone uses correct ref (tag vs semver)
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from comfygit_core.models.shared import NodeInfo
from comfygit_core.services.node_lookup_service import NodeLookupService


class TestDownloadToCacheGitFallback:
    """Test git clone fallback behavior in download_to_cache."""

    @pytest.fixture
    def cache_dir(self):
        """Create a temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_git_clone_omits_ref_when_version_is_semver(self, cache_dir):
        """SHOULD clone without --branch when version looks like semver (not a git ref).

        Scenario: Node has source=registry but no download_url
        Git clone fallback should NOT use semver "1.11.1" as --branch
        """
        # ARRANGE
        node_info = NodeInfo(
            name="ComfyUI-AKatz-Nodes",
            registry_id="comfyui-akatz-nodes",
            repository="https://github.com/akatz-ai/comfyui-akatz-nodes",
            version="1.11.1",  # Semver, not a git tag
            download_url=None,  # No download URL - triggers git fallback
            source="registry"
        )

        service = NodeLookupService(cache_path=cache_dir)

        # Mock at the utils.git module level where it's imported from
        with patch('comfygit_core.utils.git.git_clone') as mock_git_clone:
            # ACT
            service.download_to_cache(node_info)

            # ASSERT
            mock_git_clone.assert_called_once()
            call_kwargs = mock_git_clone.call_args
            # Should NOT pass the semver as ref - ref should be None
            assert call_kwargs.kwargs.get('ref') is None, \
                f"Git clone should not use semver '1.11.1' as ref, got: {call_kwargs}"

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
