"""Integration test for registry node update with empty downloadUrl.

Tests the scenario where the ComfyUI Registry API returns an empty downloadUrl
for a node version, which should trigger a fallback or be handled gracefully.

This is a regression test for the bug where:
1. Node is installed from registry with valid downloadUrl
2. User runs update, registry API returns version with empty downloadUrl
3. Update flow calls get_node() but NOT install_node() to get complete version data
4. Installation fails because download_url is empty
"""
from unittest.mock import patch

import pytest
from comfygit_core.confirmation import AutoConfirmStrategy
from comfygit_core.models.exceptions import CDEnvironmentError
from comfygit_core.models.registry import RegistryNodeInfo, RegistryNodeVersion
from comfygit_core.models.shared import NodeInfo


class TestRegistryNodeUpdateEmptyDownloadUrl:
    """Test registry node updates when API returns empty downloadUrl."""

    def test_update_fails_clearly_when_install_metadata_is_unavailable(self, test_env):
        """Test update fails clearly when complete install metadata is unavailable.

        Given: Node v1.8.0 is installed with valid downloadUrl
        When: User updates and the registry install endpoint has no v2.1.0 payload
        Then: Update should fail before mutating the installed node.
        """
        # ARRANGE: Install initial version 1.8.0 with valid downloadUrl
        node_info_v1_8_0 = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="1.8.0",
            download_url="https://example.com/v1.8.0.zip",
            repository="https://github.com/example/test-node"
        )

        cache_path_v1 = test_env.workspace_paths.cache / "custom_nodes" / "store" / "hash-v1-8-0" / "content"
        cache_path_v1.mkdir(parents=True, exist_ok=True)
        (cache_path_v1 / "__init__.py").write_text("# v1.8.0")

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            mock_get_node.return_value = node_info_v1_8_0
            mock_download.return_value = cache_path_v1
            mock_scan.return_value = []

            test_env.node_manager.add_node("test-node@1.8.0", no_test=True)

        # Verify v1.8.0 is installed
        nodes = test_env.pyproject.nodes.get_existing()
        assert nodes["test-node"].version == "1.8.0"

        # Setup mocks for update operation
        # Mock registry client to return v2.1.0 with EMPTY downloadUrl (the bug!)
        registry_node_latest = RegistryNodeInfo(
            id="test-node",
            name="test-node",
            description="Test node",
            repository="https://github.com/example/test-node",
            latest_version=RegistryNodeVersion(
                changelog="",
                dependencies=[],
                deprecated=False,
                id="test-node-v2.1.0",
                version="2.1.0",
                download_url=""  # ← BUG: Empty string from API!
            )
        )

        with patch.object(test_env.node_manager.node_lookup.registry_client, 'get_node') as mock_registry_get:
            mock_registry_get.return_value = registry_node_latest

            strategy = AutoConfirmStrategy()

            with pytest.raises(CDEnvironmentError) as exc_info:
                test_env.node_manager.update_node("test-node", confirmation_strategy=strategy, no_test=True)

            assert "Failed to get install metadata" in str(exc_info.value)

        # Verify old node is preserved after failed update (atomic rollback)
        nodes = test_env.pyproject.nodes.get_existing()
        assert "test-node" in nodes, "Old node should be preserved after failed update"
        assert nodes["test-node"].version == "1.8.0", "Old version should still be installed"

    def test_update_succeeds_when_install_endpoint_called(self, test_env):
        """Test update succeeds when install_node() endpoint is called to get complete data.

        Given: Node v1.8.0 is installed
        When: User updates and we call BOTH get_node() AND install_node()
        Then: Update succeeds with complete version data including downloadUrl

        This is the FIXED behavior we want.
        """
        # ARRANGE: Install initial version 1.8.0
        node_info_v1_8_0 = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="1.8.0",
            download_url="https://example.com/v1.8.0.zip",
            repository="https://github.com/example/test-node"
        )

        cache_path_v1 = test_env.workspace_paths.cache / "custom_nodes" / "store" / "hash-v1-8-0" / "content"
        cache_path_v1.mkdir(parents=True, exist_ok=True)
        (cache_path_v1 / "__init__.py").write_text("# v1.8.0")

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            mock_get_node.return_value = node_info_v1_8_0
            mock_download.return_value = cache_path_v1
            mock_scan.return_value = []

            test_env.node_manager.add_node("test-node@1.8.0", no_test=True)

        # Verify v1.8.0 is installed
        nodes = test_env.pyproject.nodes.get_existing()
        assert nodes["test-node"].version == "1.8.0"

        # Setup mocks for FIXED update operation
        # Mock get_node() returns incomplete data (empty downloadUrl)
        registry_node_incomplete = RegistryNodeInfo(
            id="test-node",
            name="test-node",
            description="Test node",
            repository="https://github.com/example/test-node",
            latest_version=RegistryNodeVersion(
                changelog="",
                dependencies=[],
                deprecated=False,
                id="test-node-v2.1.0",
                version="2.1.0",
                download_url=""  # Empty from get_node()
            )
        )

        # Mock install_node() returns COMPLETE data with downloadUrl
        complete_version = RegistryNodeVersion(
            changelog="",
            dependencies=[],
            deprecated=False,
            id="test-node-v2.1.0",
            version="2.1.0",
            download_url="https://cdn.comfy.org/example/test-node/2.1.0/node.zip"  # ← Complete!
        )

        cache_path_v2 = test_env.workspace_paths.cache / "custom_nodes" / "store" / "hash-v2-1-0" / "content"
        cache_path_v2.mkdir(parents=True, exist_ok=True)
        (cache_path_v2 / "__init__.py").write_text("# v2.1.0")

        with patch.object(test_env.node_manager.node_lookup.registry_client, 'get_node') as mock_registry_get, \
             patch.object(test_env.node_manager.node_lookup.registry_client, 'install_node') as mock_install, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            mock_registry_get.return_value = registry_node_incomplete
            mock_install.return_value = complete_version  # ← Returns complete data!
            mock_download.return_value = cache_path_v2
            mock_scan.return_value = []

            strategy = AutoConfirmStrategy()

            # ACT: Update node (should succeed with fix)
            result = test_env.node_manager.update_node("test-node", confirmation_strategy=strategy, no_test=True)

            # ASSERT: Update succeeded
            assert result.changed, "Update should report changes"
            assert result.new_version == "2.1.0", f"Expected new version 2.1.0, got {result.new_version}"
            assert result.old_version == "1.8.0", f"Expected old version 1.8.0, got {result.old_version}"

            # Verify install_node() was called with correct version
            mock_install.assert_called_once_with("test-node", "2.1.0")

            # Verify in pyproject.toml
            nodes = test_env.pyproject.nodes.get_existing()
            assert nodes["test-node"].version == "2.1.0"
            assert nodes["test-node"].download_url == "https://cdn.comfy.org/example/test-node/2.1.0/node.zip"
