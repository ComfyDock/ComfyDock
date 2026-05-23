"""Integration tests for version-specific node add and replacement behavior.

Tests the following scenarios:
1. Adding a new node with specific version (should install that version)
2. Adding same node, same version (should fail - already exists)
3. Adding same node, different version for regular nodes (should auto-replace)
4. Adding same node, different version for dev nodes (should require confirmation)
5. Adding same node, different version for dev nodes with --force (should auto-replace)
6. Using node update without version (should update to latest)
"""
from unittest.mock import MagicMock, patch

import pytest
from comfygit_core.models.exceptions import CDNodeConflictError
from comfygit_core.models.shared import NodeInfo


class TestNodeVersionReplacement:
    """Test version-specific node installation and replacement."""

    def test_add_new_node_with_specific_version(self, test_env):
        """Test adding a new node with specific version installs that version.

        Given: No node is installed
        When: User runs `cfd node add pkg@1.0.0`
        Then: Node pkg version 1.0.0 is installed
        """
        # Mock node info for version 1.0.0
        node_info_v1 = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="1.0.0",
            download_url="https://example.com/v1.zip"
        )

        cache_path = test_env.workspace_paths.cache / "custom_nodes" / "store" / "test-hash-v1" / "content"
        cache_path.mkdir(parents=True, exist_ok=True)
        (cache_path / "__init__.py").write_text("# Test node v1.0.0")

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            mock_get_node.return_value = node_info_v1
            mock_download.return_value = cache_path
            mock_scan.return_value = []

            # ACT: Add node with specific version
            result = test_env.node_manager.add_node("test-node@1.0.0", no_test=True)

            # ASSERT: Node is installed with correct version
            assert result.name == "test-node"
            assert result.version == "1.0.0"

            # Verify in pyproject.toml
            nodes = test_env.pyproject.nodes.get_existing()
            assert "test-node" in nodes
            assert nodes["test-node"].version == "1.0.0"

            # Verify on filesystem
            node_path = test_env.custom_nodes_path / "test-node"
            assert node_path.exists()

    def test_add_same_node_same_version_fails(self, test_env):
        """Test adding a node with same version as installed fails.

        Given: Node pkg version 1.0.0 is installed
        When: User runs `cfd node add pkg@1.0.0`
        Then: Error raised indicating node already exists
        """
        # Install initial version
        node_info = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="1.0.0"
        )

        cache_path = test_env.workspace_paths.cache / "custom_nodes" / "store" / "test-hash" / "content"
        cache_path.mkdir(parents=True, exist_ok=True)
        (cache_path / "__init__.py").write_text("# Test node")

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            mock_get_node.return_value = node_info
            mock_download.return_value = cache_path
            mock_scan.return_value = []

            # Install first time
            test_env.node_manager.add_node("test-node@1.0.0", no_test=True)

            # ACT & ASSERT: Try to install same version again
            with pytest.raises(CDNodeConflictError) as exc_info:
                test_env.node_manager.add_node("test-node@1.0.0", no_test=True)

            assert "already installed" in str(exc_info.value).lower()

    def test_add_different_version_regular_node_auto_replaces(self, test_env):
        """Test adding different version of regular node auto-replaces.

        Given: Node pkg version 1.0.0 is installed (regular node from registry)
        When: User runs `cfd node add pkg@2.0.0`
        Then: Version 1.0.0 is removed and version 2.0.0 is installed automatically
        """
        # Install initial version 1.0.0
        node_info_v1 = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="1.0.0"
        )

        cache_path_v1 = test_env.workspace_paths.cache / "custom_nodes" / "store" / "hash-v1" / "content"
        cache_path_v1.mkdir(parents=True, exist_ok=True)
        (cache_path_v1 / "__init__.py").write_text("# v1.0.0")

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            mock_get_node.return_value = node_info_v1
            mock_download.return_value = cache_path_v1
            mock_scan.return_value = []

            test_env.node_manager.add_node("test-node@1.0.0", no_test=True)

        # Verify v1.0.0 is installed
        nodes = test_env.pyproject.nodes.get_existing()
        assert nodes["test-node"].version == "1.0.0"

        # Now install version 2.0.0
        node_info_v2 = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="2.0.0"
        )

        cache_path_v2 = test_env.workspace_paths.cache / "custom_nodes" / "store" / "hash-v2" / "content"
        cache_path_v2.mkdir(parents=True, exist_ok=True)
        (cache_path_v2 / "__init__.py").write_text("# v2.0.0")

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            mock_get_node.return_value = node_info_v2
            mock_download.return_value = cache_path_v2
            mock_scan.return_value = []

            # ACT: Install different version (should auto-replace)
            result = test_env.node_manager.add_node("test-node@2.0.0", no_test=True)

            # ASSERT: Version 2.0.0 is now installed
            assert result.version == "2.0.0"

            nodes = test_env.pyproject.nodes.get_existing()
            assert nodes["test-node"].version == "2.0.0"

            # Only one version exists
            assert len([k for k in nodes.keys() if "test-node" in k]) == 1

    def test_add_different_version_dev_node_requires_confirmation(self, test_env):
        """Test adding different version of dev node requires confirmation.

        Given: Node pkg is installed as dev node (source='development')
        When: User runs `cfd node add pkg@1.0.0` (without --force)
        Then: User is prompted for confirmation before replacement
        """
        # Manually create a dev node
        node_path = test_env.custom_nodes_path / "test-node"
        node_path.mkdir(parents=True)
        (node_path / "__init__.py").write_text("# Dev node")

        # Track as dev node
        test_env.node_manager.add_node("test-node", is_development=True, no_test=True)

        # Verify it's tracked as dev
        nodes = test_env.pyproject.nodes.get_existing()
        assert nodes["test-node"].source == "development"
        assert nodes["test-node"].version == "dev"

        # Try to install a registry version
        node_info_registry = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="1.0.0"
        )

        cache_path = test_env.workspace_paths.cache / "custom_nodes" / "store" / "hash" / "content"
        cache_path.mkdir(parents=True, exist_ok=True)
        (cache_path / "__init__.py").write_text("# v1.0.0")

        # Mock a confirmation strategy that denies
        mock_strategy = MagicMock()
        mock_strategy.confirm_replace_dev_node.return_value = False

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            mock_get_node.return_value = node_info_registry
            mock_download.return_value = cache_path
            mock_scan.return_value = []

            # ACT & ASSERT: Should raise error when user denies confirmation
            with pytest.raises(CDNodeConflictError):
                test_env.node_manager.add_node(
                    "test-node@1.0.0",
                    no_test=True,
                    confirmation_strategy=mock_strategy
                )

            # Verify confirmation was requested
            mock_strategy.confirm_replace_dev_node.assert_called_once()

            # Verify dev node is still there
            nodes = test_env.pyproject.nodes.get_existing()
            assert nodes["test-node"].source == "development"

    def test_add_different_version_dev_node_with_force_auto_replaces(self, test_env):
        """Test adding different version of dev node with --force auto-replaces.

        Given: Node pkg is installed as dev node
        When: User runs `cfd node add pkg@1.0.0 --force`
        Then: Dev node is replaced without confirmation
        """
        # Create dev node
        node_path = test_env.custom_nodes_path / "test-node"
        node_path.mkdir(parents=True)
        (node_path / "__init__.py").write_text("# Dev node")
        test_env.node_manager.add_node("test-node", is_development=True, no_test=True)

        # Install registry version with force=True
        node_info_registry = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="1.0.0"
        )

        cache_path = test_env.workspace_paths.cache / "custom_nodes" / "store" / "hash" / "content"
        cache_path.mkdir(parents=True, exist_ok=True)
        (cache_path / "__init__.py").write_text("# v1.0.0")

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            mock_get_node.return_value = node_info_registry
            mock_download.return_value = cache_path
            mock_scan.return_value = []

            # ACT: Force replace dev node
            result = test_env.node_manager.add_node("test-node@1.0.0", no_test=True, force=True)

            # ASSERT: Registry version is installed
            assert result.version == "1.0.0"

            nodes = test_env.pyproject.nodes.get_existing()
            assert nodes["test-node"].source == "registry"
            assert nodes["test-node"].version == "1.0.0"

    def test_add_without_version_on_existing_node_fails(self, test_env):
        """Test adding a node without version when already installed fails.

        Given: Node pkg version 1.0.0 is installed
        When: User runs `cfd node add pkg` (no version specified, latest is 2.0.0)
        Then: Error raised - node already exists (doesn't auto-upgrade)

        This validates that 'add' without version means "install new" not "upgrade to latest".
        Users should use 'node update' for upgrading.
        """
        # Install version 1.0.0
        node_info_v1 = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="1.0.0"
        )

        cache_path_v1 = test_env.workspace_paths.cache / "custom_nodes" / "store" / "hash-v1" / "content"
        cache_path_v1.mkdir(parents=True, exist_ok=True)
        (cache_path_v1 / "__init__.py").write_text("# v1.0.0")

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            mock_get_node.return_value = node_info_v1
            mock_download.return_value = cache_path_v1
            mock_scan.return_value = []

            test_env.node_manager.add_node("test-node@1.0.0", no_test=True)

        # Verify v1.0.0 is installed
        nodes = test_env.pyproject.nodes.get_existing()
        assert nodes["test-node"].version == "1.0.0"

        # Try to add again without version (registry would return latest = 2.0.0)
        node_info_v2_latest = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="2.0.0"  # Latest version from registry
        )

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node:
            mock_get_node.return_value = node_info_v2_latest

            # ACT & ASSERT: Should fail - node already exists
            # Even though latest is 2.0.0, we don't auto-upgrade
            with pytest.raises(CDNodeConflictError) as exc_info:
                test_env.node_manager.add_node("test-node", no_test=True)

            error_msg = str(exc_info.value).lower()
            assert "already installed" in error_msg or "already exists" in error_msg

        # Verify version didn't change
        nodes = test_env.pyproject.nodes.get_existing()
        assert nodes["test-node"].version == "1.0.0", "Version should not have changed"

    def test_update_node_uses_latest_from_api_not_cache(self, test_env):
        """Test node update fetches latest version from API, not stale cache.

        Given: Node pkg v1.8.0 is installed, and cache has v1.8.0 as latest
        When: User runs `cfd node update pkg` and API reports v2.1.0 is latest
        Then: Node is updated to v2.1.0 (from API), not v1.8.0 (from cache)

        This is a regression test for the bug where update_node() would:
        1. Query registry API and find v2.1.0
        2. Remove old v1.8.0
        3. Call add_node(registry_id) without @version
        4. add_node would use stale cache showing v1.8.0 as latest
        5. Re-install v1.8.0 instead of v2.1.0
        """
        from comfygit_core.confirmation import AutoConfirmStrategy
        from comfygit_core.models.registry import RegistryNodeInfo, RegistryNodeVersion

        # ARRANGE: Install initial version 1.8.0
        node_info_v1_8_0 = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="1.8.0",
            download_url="https://example.com/v1.8.0.zip"
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
        # Mock registry client to return v2.1.0 as latest
        registry_node_latest = RegistryNodeInfo(
            id="test-node",
            name="test-node",
            description="Test node for testing",
            repository="https://github.com/example/test-node",
            latest_version=RegistryNodeVersion(
                changelog="",
                dependencies=[],
                deprecated=False,
                id="test-node-v2.1.0",
                version="2.1.0",
                download_url="https://example.com/v2.1.0.zip"
            )
        )

        node_info_v2_1_0 = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="2.1.0",
            download_url="https://example.com/v2.1.0.zip"
        )

        # Simulate stale cache returning v1.8.0 when no version specified
        node_info_stale_cache = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="1.8.0",  # STALE - cache hasn't been updated
            download_url="https://example.com/v1.8.0.zip"
        )

        cache_path_v2 = test_env.workspace_paths.cache / "custom_nodes" / "store" / "hash-v2-1-0" / "content"
        cache_path_v2.mkdir(parents=True, exist_ok=True)
        (cache_path_v2 / "__init__.py").write_text("# v2.1.0")

        with patch.object(test_env.node_manager.node_lookup.registry_client, 'get_node') as mock_registry_get, \
             patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            # Registry client returns latest v2.1.0
            mock_registry_get.return_value = registry_node_latest

            # Mock get_node to simulate cache behavior:
            # - First call (when checking in update): return stale cache (this is what happens in real bug)
            # - If called with @version, return correct version
            def get_node_side_effect(identifier):
                if '@' in identifier:
                    # Version specified - return correct version
                    return node_info_v2_1_0
                else:
                    # No version - return stale cache
                    # BUG: This is what currently happens and causes the issue
                    return node_info_stale_cache

            mock_get_node.side_effect = get_node_side_effect
            mock_download.return_value = cache_path_v2
            mock_scan.return_value = []

            # ACT: Update node (should use fresh API data, not cache)
            strategy = AutoConfirmStrategy()
            result = test_env.node_manager.update_node("test-node", confirmation_strategy=strategy, no_test=True)

            # ASSERT: Node should be updated to v2.1.0 from API, NOT v1.8.0 from cache
            assert result.changed, "Update should report changes"
            assert result.new_version == "2.1.0", f"Expected new version 2.1.0, got {result.new_version}"
            assert result.old_version == "1.8.0", f"Expected old version 1.8.0, got {result.old_version}"

            # Verify in pyproject.toml
            nodes = test_env.pyproject.nodes.get_existing()
            assert nodes["test-node"].version == "2.1.0", \
                f"Expected version 2.1.0 in pyproject, got {nodes['test-node'].version}"

    def test_add_node_with_version_uses_api_not_cache(self, test_env):
        """Test adding a node with @version uses API, not stale cache.

        Given: Cache doesn't have version 2.1.0 yet (only has up to 1.8.0)
        When: User runs `cfd node add pkg@2.1.0`
        Then: Node is installed with v2.1.0 from API, not rejected due to cache miss

        This ensures that users can install specific versions that exist on the
        registry/GitHub but haven't been synced to the local cache yet.
        """
        from comfygit_core.models.registry import RegistryNodeInfo, RegistryNodeVersion

        # Setup: User wants to install a specific version that's not in cache
        node_info_v2_1_0 = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry",
            version="2.1.0",
            download_url="https://example.com/v2.1.0.zip"
        )

        # Mock registry to have this version available
        registry_node = RegistryNodeInfo(
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
                download_url="https://example.com/v2.1.0.zip"
            )
        )

        cache_path = test_env.workspace_paths.cache / "custom_nodes" / "store" / "hash-v2-1-0" / "content"
        cache_path.mkdir(parents=True, exist_ok=True)
        (cache_path / "__init__.py").write_text("# v2.1.0")

        with patch.object(test_env.node_manager.node_lookup, 'get_node') as mock_get_node, \
             patch.object(test_env.node_manager.node_lookup.registry_client, 'get_node') as mock_registry_get, \
             patch.object(test_env.node_manager.node_lookup.registry_client, 'install_node') as mock_install_node, \
             patch.object(test_env.node_manager.node_lookup, 'download_to_cache') as mock_download, \
             patch.object(test_env.node_manager.node_lookup, 'scan_requirements') as mock_scan:

            # When user specifies @version, get_node should call registry API
            mock_get_node.return_value = node_info_v2_1_0
            mock_registry_get.return_value = registry_node
            mock_install_node.return_value = registry_node.latest_version
            mock_download.return_value = cache_path
            mock_scan.return_value = []

            # ACT: Add node with specific version
            result = test_env.node_manager.add_node("test-node@2.1.0", no_test=True)

            # ASSERT: Node installed with correct version from API
            assert result.version == "2.1.0", f"Expected version 2.1.0, got {result.version}"

            # Verify in pyproject.toml
            nodes = test_env.pyproject.nodes.get_existing()
            assert nodes["test-node"].version == "2.1.0", \
                f"Expected version 2.1.0 in pyproject, got {nodes['test-node'].version}"

            # Verify get_node was called with @version (important!)
            mock_get_node.assert_called_once_with("test-node@2.1.0")
