"""Integration test for registry git fallback behavior.

When a registry node has metadata but no download URL, the system should
fallback to cloning from the repository URL instead of failing.
"""
from unittest.mock import patch

import pytest
from comfygit_core.models.registry import RegistryNodeInfo, RegistryNodeVersion


class TestRegistryGitFallback:
    """Test git fallback when registry node has no download URL."""

    def test_node_without_download_url_falls_back_to_git(self, test_env):
        """
        When registry node has no download URL, should clone from repository.

        Scenario:
        - Registry returns node metadata (name, repo URL, etc.)
        - Registry install endpoint returns 404 (no download URL)
        - System should detect this and fallback to git clone from repository URL
        - Node should be successfully installed via git

        Real-world case: ComfyUI_Comfyroll_CustomNodes, masquerade-nodes-comfyui
        """
        # ARRANGE - Mock registry to return node without download URL
        mock_registry_node = RegistryNodeInfo(
            id="test-node-without-cdn",
            name="Test Node Without CDN",
            description="Test node that has no CDN package",
            author="test-author",
            license="MIT",
            icon="",
            repository="https://github.com/test-user/test-node-without-cdn",
            tags=[],
            latest_version=None  # No version info = no download URL
        )

        # Mock registry client to return node info but no install info
        with patch.object(test_env.node_manager.node_lookup.registry_client, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup.registry_client, 'install_node') as mock_install, \
             patch('comfygit_core.utils.git.git_clone') as mock_git_clone:

            mock_get_node.return_value = mock_registry_node
            mock_install.return_value = None  # No install info available

            # Mock git clone to create a minimal node structure
            def mock_git_clone_side_effect(url, dest, **kwargs):
                dest.mkdir(parents=True, exist_ok=True)
                (dest / ".git").mkdir()
                (dest / "__init__.py").write_text("# Test node")
            mock_git_clone.side_effect = mock_git_clone_side_effect

            # ACT - Try to add the node
            test_env.add_node("test-node-without-cdn", no_test=True)

            # ASSERT - Node should be installed via git fallback
            # Note: Node name from registry is used for directory name
            installed_path = test_env.custom_nodes_path / mock_registry_node.name
            assert installed_path.exists(), \
                f"Node should be installed via git fallback even without registry CDN URL. Expected: {installed_path}"

            # Verify it's a git clone (has .git directory)
            assert (installed_path / ".git").exists(), \
                "Node should be git cloned (not downloaded from CDN)"

            # Verify node is tracked in pyproject.toml
            config = test_env.pyproject.load()
            nodes = config.get("tool", {}).get("comfygit", {}).get("nodes", {})
            assert "test-node-without-cdn" in nodes, \
                "Node should be tracked in pyproject.toml"

            # Verify source is marked as git (not registry)
            node_config = nodes["test-node-without-cdn"]
            assert node_config.get("source") == "git", \
                "Node source should be 'git' when using fallback"
            assert node_config.get("repository") == mock_registry_node.repository, \
                "Repository URL should be preserved"

    def test_registry_node_with_download_url_uses_cdn(self, test_env):
        """
        When registry node HAS download URL, should use CDN (not git fallback).

        Ensures we don't break existing behavior for nodes with proper CDN packages.
        """
        # ARRANGE - Mock registry node WITH download URL
        mock_registry_node = RegistryNodeInfo(
            id="test-node-with-cdn",
            name="Test Node With CDN",
            description="Test node with proper CDN package",
            author="test-author",
            license="MIT",
            icon="",
            repository="https://github.com/test-user/test-node-with-cdn",
            tags=[],
            latest_version=RegistryNodeVersion(
                changelog="",
                dependencies=[],
                deprecated=False,
                id="version-id",
                version="1.0.0",
                download_url="https://cdn.comfy.org/test-user/test-node-with-cdn/1.0.0/node.zip"
            )
        )

        with patch.object(test_env.node_manager.node_lookup.registry_client, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup.registry_client, 'install_node') as mock_install, \
             patch('comfygit_core.utils.download.download_and_extract_archive') as mock_download:

            mock_get_node.return_value = mock_registry_node
            mock_install.return_value = mock_registry_node.latest_version

            # Mock successful download
            def mock_download_side_effect(url, dest):
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "test_file.py").write_text("# test")
            mock_download.side_effect = mock_download_side_effect

            # ACT
            test_env.add_node("test-node-with-cdn", no_test=True)

            # ASSERT - Should use CDN download, not git
            mock_download.assert_called_once()
            assert mock_download.call_args[0][0] == mock_registry_node.latest_version.download_url

            # Verify source is registry (not git)
            config = test_env.pyproject.load()
            nodes = config.get("tool", {}).get("comfygit", {}).get("nodes", {})
            assert nodes["test-node-with-cdn"].get("source") == "registry"

    def test_missing_repository_url_fails_gracefully(self, test_env):
        """
        When registry node has no download URL AND no repository, should fail clearly.

        Edge case: Some registry entries might be incomplete.
        """
        # ARRANGE - Mock node with neither download URL nor repository
        mock_registry_node = RegistryNodeInfo(
            id="broken-node",
            name="Broken Node",
            description="Node with incomplete registry data",
            author="test-author",
            license="MIT",
            icon="",
            repository="",  # Empty repository URL
            tags=[],
            latest_version=None
        )

        with patch.object(test_env.node_manager.node_lookup.registry_client, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup.registry_client, 'install_node') as mock_install:

            mock_get_node.return_value = mock_registry_node
            mock_install.return_value = None

            # ACT & ASSERT - Should raise clear error
            from comfygit_core.models.exceptions import CDEnvironmentError
            with pytest.raises(CDEnvironmentError) as exc_info:
                test_env.add_node("broken-node", no_test=True)

            # Error message should be clear about what's missing
            assert "repository" in str(exc_info.value).lower() or "download" in str(exc_info.value).lower(), \
                "Error should clearly indicate missing repository/download URL"
