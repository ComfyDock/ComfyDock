"""Test that arbitrary GitHub URLs can be installed (not just registry packages)."""

from unittest.mock import Mock

import pytest
from comfygit_core.managers.node_manager import NodeManager
from comfygit_core.models.shared import NodeInfo


class TestGitHubURLInstallation:
    """Test installation of arbitrary GitHub URLs (not in registry)."""

    @pytest.fixture
    def mock_node_manager(self, tmp_path):
        """Create a NodeManager with mocked dependencies."""
        pyproject = Mock()
        pyproject.nodes.get_existing.return_value = {}
        pyproject.nodes.add = Mock()
        pyproject.snapshot.return_value = {}
        pyproject.restore = Mock()
        pyproject.uv_config.get_source_names.return_value = set()

        uv = Mock()
        uv.add_requirements_with_sources = Mock()
        uv.sync_project = Mock()

        node_lookup = Mock()
        resolution_tester = Mock()
        custom_nodes_path = tmp_path / "custom_nodes"
        custom_nodes_path.mkdir()

        # Create mock node repository
        node_repository = Mock()
        node_repository.resolve_github_url = Mock()

        manager = NodeManager(
            pyproject=pyproject,
            uv=uv,
            node_lookup=node_lookup,
            resolution_tester=resolution_tester,
            custom_nodes_path=custom_nodes_path,
            node_repository=node_repository
        )

        return manager

    def test_github_url_not_in_registry_installs_as_git_node(self, mock_node_manager, tmp_path):
        """Test that a GitHub URL NOT in the registry can still be installed as a git node."""

        # Setup: GitHub URL that's NOT in the registry
        github_url = "https://github.com/logtd/ComfyUI-HotReloadHack.git"

        # Mock node repository to return None (not in registry)
        mock_node_manager.node_repository.resolve_github_url = Mock(return_value=None)

        # Mock node lookup to return git node info (simulates GitHub API call)
        git_node_info = NodeInfo(
            name="ComfyUI-HotReloadHack",
            repository=github_url,
            source="git",
            version="abc123def456"
        )
        mock_node_manager.node_lookup.get_node = Mock(return_value=git_node_info)

        # Mock download and requirements
        cache_path = tmp_path / "cache" / "ComfyUI-HotReloadHack"
        cache_path.mkdir(parents=True)
        mock_node_manager.node_lookup.download_to_cache = Mock(return_value=cache_path)
        mock_node_manager.node_lookup.scan_requirements = Mock(return_value=[])

        # Mock resolution testing
        test_result = Mock()
        test_result.success = True
        mock_node_manager._test_requirements_in_isolation = Mock(return_value=test_result)

        # Act: Install the GitHub URL
        result = mock_node_manager.add_node(github_url, no_test=False, force=False)

        # Assert: Installation succeeded
        assert result.name == "ComfyUI-HotReloadHack"
        assert result.source == "git"
        assert result.repository == github_url
        assert result.registry_id is None  # Pure git node - no registry ID

        # Verify node lookup was called with the GitHub URL
        mock_node_manager.node_lookup.get_node.assert_called_once_with(github_url)

        # Verify node was added to pyproject
        mock_node_manager.pyproject.nodes.add.assert_called_once()

    def test_github_url_in_registry_uses_registry_id(self, mock_node_manager, tmp_path):
        """Test that a GitHub URL that IS in the registry gets resolved to registry ID."""

        # Setup: GitHub URL that IS in the registry
        github_url = "https://github.com/ltdrdata/ComfyUI-Manager.git"
        registry_id = "comfyui-manager"

        # Mock node repository to return registry package
        resolved_package = Mock()
        resolved_package.id = registry_id
        mock_node_manager.node_repository.resolve_github_url = Mock(return_value=resolved_package)

        # Mock that it's not already installed
        mock_node_manager._get_existing_node_by_registry_id = Mock(return_value={})

        # Mock node lookup to return registry node info
        registry_node_info = NodeInfo(
            name="ComfyUI-Manager",
            registry_id=registry_id,
            repository=github_url,
            source="registry",
            version="1.0.0"
        )
        mock_node_manager.node_lookup.get_node = Mock(return_value=registry_node_info)

        # Mock download and requirements
        cache_path = tmp_path / "cache" / "ComfyUI-Manager"
        cache_path.mkdir(parents=True)
        mock_node_manager.node_lookup.download_to_cache = Mock(return_value=cache_path)
        mock_node_manager.node_lookup.scan_requirements = Mock(return_value=[])

        # Mock resolution testing
        test_result = Mock()
        test_result.success = True
        mock_node_manager._test_requirements_in_isolation = Mock(return_value=test_result)

        # Act: Install the GitHub URL
        result = mock_node_manager.add_node(github_url, no_test=False, force=False)

        # Assert: Uses registry ID (preferred over git)
        assert result.registry_id == registry_id
        assert result.source == "registry"

    def test_find_node_by_name_detects_duplicates(self, mock_node_manager):
        """Test that _find_node_by_name correctly identifies existing nodes."""

        # Setup: A node already installed
        existing_node = NodeInfo(
            name="ComfyUI-AwesomeNode",
            repository="https://github.com/owner/ComfyUI-AwesomeNode.git",
            source="git",
            version="abc123"
        )
        mock_node_manager.pyproject.nodes.get_existing.return_value = {
            "ComfyUI-AwesomeNode": existing_node
        }

        # Act: Try to find by name
        result = mock_node_manager._find_node_by_name("ComfyUI-AwesomeNode")

        # Assert: Node is found
        assert result is not None
        identifier, node_info = result
        assert identifier == "ComfyUI-AwesomeNode"
        assert node_info.name == "ComfyUI-AwesomeNode"
        assert node_info.source == "git"

    def test_find_node_by_name_is_case_insensitive(self, mock_node_manager):
        """Test that _find_node_by_name works case-insensitively."""

        # Setup
        existing_node = NodeInfo(
            name="ComfyUI-AwesomeNode",
            source="git"
        )
        mock_node_manager.pyproject.nodes.get_existing.return_value = {
            "ComfyUI-AwesomeNode": existing_node
        }

        # Act: Search with different case
        result = mock_node_manager._find_node_by_name("comfyui-awesomenode")

        # Assert: Still finds it
        assert result is not None
        identifier, node_info = result
        assert node_info.name == "ComfyUI-AwesomeNode"
