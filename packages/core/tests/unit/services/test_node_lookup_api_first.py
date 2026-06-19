"""Tests for NodeLookupService API-first behavior.

TDD tests to verify that NodeLookupService:
1. ALWAYS queries the live registry API first (no cache preference)
2. Falls back to local node mappings cache only if API fails or is unreachable
3. The prefer_registry_cache config option has been removed

This replaces the old cache-first behavior where prefer_registry_cache=True
would check local cache before hitting the API.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from comfygit_core.clients.github_client import GitHubRepoInfo
from comfygit_core.models.registry import RegistryNodeInfo, RegistryNodeVersion
from comfygit_core.repositories.node_mappings_repository import NodeMappingsRepository
from comfygit_core.services.node_lookup_service import NodeLookupService


class TestNodeLookupAPIFirst:
    """Test API-first lookup behavior - always queries live API first."""

    @pytest.fixture
    def mock_mappings_data(self):
        """Create mock mappings JSON data."""
        return {
            "version": "2025.01.01",
            "generated_at": "2025-01-01T00:00:00",
            "stats": {
                "packages": 1,
                "signatures": 1,
                "total_nodes": 1,
                "augmented": True,
                "augmentation_date": "2025-01-01T00:00:00",
                "nodes_from_manager": 0,
                "manager_packages": 0
            },
            "mappings": {},
            "packages": {
                "test-package-id": {
                    "id": "test-package-id",
                    "display_name": "Test Package",
                    "author": "test-author",
                    "description": "Test description",
                    "repository": "https://github.com/test/repo",
                    "downloads": 100,
                    "github_stars": 50,
                    "rating": None,
                    "license": "MIT",
                    "category": "test",
                    "icon": None,
                    "tags": [],
                    "status": "active",
                    "created_at": "2025-01-01T00:00:00",
                    "source": None,
                    "versions": {
                        "1.0.0": {
                            "version": "1.0.0",
                            "changelog": "Initial release",
                            "release_date": "2025-01-01T00:00:00",
                            "dependencies": [],
                            "deprecated": False,
                            "download_url": "https://cdn.comfy.org/test-package-id/1.0.0/node.zip",
                            "status": "active",
                            "supported_accelerators": None,
                            "supported_comfyui_version": None,
                            "supported_os": None
                        }
                    }
                }
            }
        }

    @pytest.fixture
    def cache_dir(self):
        """Create a temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def mappings_repo(self, mock_mappings_data):
        """Create a NodeMappingsRepository with test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mappings_path = Path(tmpdir) / "mappings.json"
            mappings_path.write_text(json.dumps(mock_mappings_data))

            mock_data_manager = Mock()
            mock_data_manager.get_mappings_path.return_value = mappings_path

            repo = NodeMappingsRepository(data_manager=mock_data_manager)
            yield repo

    def test_find_node_always_queries_api_first(self, mappings_repo, cache_dir):
        """SHOULD always query registry API first, even when package is in local cache."""
        # ARRANGE
        mock_registry_client = MagicMock()

        # Mock registry returning the package
        mock_registry_node = RegistryNodeInfo(
            id="test-package-id",
            name="Test Package",
            description="Test description",
            repository="https://github.com/test/repo",
            latest_version=RegistryNodeVersion(
                changelog="Latest",
                dependencies=[],
                deprecated=False,
                id="test-package-id-v2.0.0",
                version="2.0.0",  # Newer version than cache
                download_url="https://cdn.comfy.org/test-package-id/2.0.0/node.zip"
            )
        )
        mock_registry_client.get_node.return_value = mock_registry_node
        mock_registry_client.install_node.return_value = mock_registry_node.latest_version

        # Create service with local cache available
        service = NodeLookupService(
            cache_path=cache_dir,
            node_mappings_repository=mappings_repo,
            # NOTE: No workspace_config_repository - the prefer_registry_cache
            # option has been removed, so this parameter should not be needed
        )
        service.registry_client = mock_registry_client

        # ACT
        result = service.find_node("test-package-id")

        # ASSERT
        # Should have called the registry API (even though package is in cache)
        mock_registry_client.get_node.assert_called_once_with("test-package-id")

        # Should return the API result (version 2.0.0), not the cached version (1.0.0)
        assert result is not None
        assert result.version == "2.0.0"
        assert result.download_url == "https://cdn.comfy.org/test-package-id/2.0.0/node.zip"

    def test_find_node_falls_back_to_cache_when_api_fails(self, mappings_repo, cache_dir):
        """SHOULD fall back to local cache when registry API is unreachable."""
        # ARRANGE
        mock_registry_client = MagicMock()
        # API throws an error (simulating network issues)
        from comfygit_core.models.exceptions import CDRegistryError
        mock_registry_client.get_node.side_effect = CDRegistryError("Network error")

        service = NodeLookupService(
            cache_path=cache_dir,
            node_mappings_repository=mappings_repo,
        )
        service.registry_client = mock_registry_client

        # ACT
        result = service.find_node("test-package-id")

        # ASSERT
        # Should have tried API first
        mock_registry_client.get_node.assert_called_once_with("test-package-id")

        # Should fall back to cached data when API fails
        assert result is not None
        assert result.name == "Test Package"
        assert result.version == "1.0.0"  # Cached version
        assert result.download_url == "https://cdn.comfy.org/test-package-id/1.0.0/node.zip"

    def test_find_node_returns_none_when_api_fails_and_not_in_cache(self, cache_dir):
        """SHOULD return None when API fails and package is not in local cache."""
        # ARRANGE
        mock_registry_client = MagicMock()
        from comfygit_core.models.exceptions import CDRegistryError
        mock_registry_client.get_node.side_effect = CDRegistryError("Network error")

        # No local cache
        service = NodeLookupService(
            cache_path=cache_dir,
            node_mappings_repository=None,
        )
        service.registry_client = mock_registry_client

        # ACT
        result = service.find_node("unknown-package")

        # ASSERT
        assert result is None

    def test_find_node_uses_git_for_explicit_nightly_registry_request(self, cache_dir):
        """SHOULD treat registry @nightly as explicit git acquisition."""
        # ARRANGE
        mock_registry_client = MagicMock()
        mock_github_client = MagicMock()

        mock_registry_node = RegistryNodeInfo(
            id="test-package-id",
            name="Test Package",
            description="Test package with nightly/git only",
            repository="https://github.com/test/repo",
            latest_version=None,
        )
        mock_registry_client.get_node.return_value = mock_registry_node
        mock_registry_client.install_node.return_value = None
        mock_github_client.get_repository_info.return_value = GitHubRepoInfo(
            owner="test",
            name="repo",
            default_branch="main",
            clone_url="https://github.com/test/repo.git",
            latest_commit="a" * 40,
        )

        service = NodeLookupService(cache_path=cache_dir)
        service.registry_client = mock_registry_client
        service.github_client = mock_github_client

        # ACT
        result = service.find_node("test-package-id@nightly")

        # ASSERT
        mock_registry_client.get_node.assert_called_once_with("test-package-id")
        mock_registry_client.install_node.assert_called_once_with("test-package-id", "nightly")
        mock_github_client.get_repository_info.assert_called_once_with("https://github.com/test/repo")

        assert result is not None
        assert result.source == "git"
        assert result.registry_id == "test-package-id"
        assert result.repository == "https://github.com/test/repo.git"
        assert result.version == "a" * 40

    def test_find_node_does_not_use_git_for_plain_registry_request_without_artifact(self, cache_dir):
        """SHOULD not silently use git when no explicit git acquisition was requested."""
        # ARRANGE
        mock_registry_client = MagicMock()
        mock_github_client = MagicMock()

        mock_registry_node = RegistryNodeInfo(
            id="test-package-id",
            name="Test Package",
            description="Test package without registry artifact",
            repository="https://github.com/test/repo",
            latest_version=None,
        )
        mock_registry_client.get_node.return_value = mock_registry_node
        mock_registry_client.install_node.return_value = None

        service = NodeLookupService(cache_path=cache_dir)
        service.registry_client = mock_registry_client
        service.github_client = mock_github_client

        # ACT
        result = service.find_node("test-package-id")

        # ASSERT
        mock_registry_client.get_node.assert_called_once_with("test-package-id")
        mock_registry_client.install_node.assert_called_once_with("test-package-id", None)
        mock_github_client.get_repository_info.assert_not_called()

        assert result is not None
        assert result.source == "registry"
        assert result.registry_id == "test-package-id"
        assert result.repository == "https://github.com/test/repo"
        assert not result.download_url

    def test_find_git_url_falls_back_to_direct_clone_metadata_when_api_fails(self, cache_dir):
        """CGSYNC-NODE-05: Git URL installs should not require GitHub API metadata."""
        mock_github_client = MagicMock()
        mock_github_client.get_repository_info.side_effect = OSError("temporary DNS failure")

        service = NodeLookupService(cache_path=cache_dir)
        service.github_client = mock_github_client

        result = service.find_node("https://github.com/m1kep/comfyliterals@main")

        mock_github_client.get_repository_info.assert_called_once_with(
            "https://github.com/m1kep/comfyliterals",
            ref="main",
        )
        assert result is not None
        assert result.name == "comfyliterals"
        assert result.repository == "https://github.com/m1kep/comfyliterals"
        assert result.source == "git"
        assert result.version == "main"


class TestWorkspaceConfigNoPreferRegistryCache:
    """Test that prefer_registry_cache has been removed from WorkspaceConfig."""

    def test_workspace_config_has_no_prefer_registry_cache_field(self):
        """SHOULD not have prefer_registry_cache field in WorkspaceConfig."""
        from comfygit_core.models.workspace_config import WorkspaceConfig

        # WorkspaceConfig should not have prefer_registry_cache attribute
        assert not hasattr(WorkspaceConfig, 'prefer_registry_cache') or \
            'prefer_registry_cache' not in WorkspaceConfig.__dataclass_fields__, \
            "prefer_registry_cache should be removed from WorkspaceConfig"

    def test_workspace_config_from_dict_ignores_prefer_registry_cache(self):
        """SHOULD silently ignore prefer_registry_cache in existing config files."""
        from comfygit_core.models.workspace_config import WorkspaceConfig

        # Old config file that has prefer_registry_cache (for backwards compat during migration)
        config_data = {
            "version": 1,
            "active_environment": "",
            "created_at": "2025-01-01T00:00:00",
            "global_model_directory": None,
            "api_credentials": None,
            "prefer_registry_cache": True  # Old field - should be ignored
        }

        # Should not raise, should just ignore the field
        config = WorkspaceConfig.from_dict(config_data)
        assert config.version == 1
        # Should not have the field
        assert not hasattr(config, 'prefer_registry_cache') or \
            getattr(config, 'prefer_registry_cache', None) is None


class TestWorkspaceConfigRepositoryNoPreferRegistryCache:
    """Test that get/set_prefer_registry_cache has been removed."""

    def test_repository_has_no_prefer_registry_cache_methods(self):
        """SHOULD not have get/set_prefer_registry_cache methods."""
        from comfygit_core.repositories.workspace_config_repository import WorkspaceConfigRepository

        # These methods should be removed
        assert not hasattr(WorkspaceConfigRepository, 'get_prefer_registry_cache'), \
            "get_prefer_registry_cache should be removed"
        assert not hasattr(WorkspaceConfigRepository, 'set_prefer_registry_cache'), \
            "set_prefer_registry_cache should be removed"
