"""Tests for NodeManager utilities."""

from unittest.mock import Mock

import pytest
from comfygit_core.managers.node_manager import NodeManager
from comfygit_core.models.exceptions import CDEnvironmentError, CDNodeConflictError
from comfygit_core.models.shared import NodeInfo
from comfygit_core.utils.git import is_github_url


class TestNodeManager:
    """Test NodeManager utility methods."""

    def test_is_github_url_https(self):
        """Test GitHub URL detection for HTTPS URLs."""
        assert is_github_url("https://github.com/owner/repo")
        assert is_github_url("https://github.com/owner/repo.git")

    def test_is_github_url_ssh(self):
        """Test GitHub URL detection for SSH URLs."""
        assert is_github_url("git@github.com:owner/repo.git")
        assert is_github_url("ssh://git@github.com/owner/repo")

    def test_is_github_url_non_github(self):
        """Test GitHub URL detection for non-GitHub URLs."""
        assert not is_github_url("https://gitlab.com/owner/repo")
        assert not is_github_url("registry-package-id")
        assert not is_github_url("local-path")
        assert not is_github_url("")

    def test_get_existing_node_by_registry_id_found(self):
        """Test getting existing node by registry ID when found."""
        mock_pyproject = Mock()
        mock_node_info = Mock()
        mock_node_info.registry_id = "test-package"
        mock_node_info.name = "Test Node"
        mock_node_info.version = "1.0.0"
        mock_node_info.repository = "https://github.com/owner/repo"
        mock_node_info.source = "git"

        mock_pyproject.nodes.get_existing.return_value = {
            "node1": mock_node_info
        }

        node_manager = NodeManager(
            mock_pyproject, Mock(), Mock(), Mock(), Mock(), Mock()
        )

        result = node_manager._get_existing_node_by_registry_id("test-package")
        expected = {
            'name': "Test Node",
            'registry_id': "test-package",
            'version': "1.0.0",
            'repository': "https://github.com/owner/repo",
            'source': "git"
        }

        assert result == expected

    def test_get_existing_node_by_registry_id_not_found(self):
        """Test getting existing node by registry ID when not found."""
        mock_pyproject = Mock()
        mock_node_info = Mock()
        mock_node_info.registry_id = "other-package"

        mock_pyproject.nodes.get_existing.return_value = {
            "node1": mock_node_info
        }

        node_manager = NodeManager(
            mock_pyproject, Mock(), Mock(), Mock(), Mock(), Mock()
        )

        result = node_manager._get_existing_node_by_registry_id("test-package")
        assert result == {}

    def test_add_node_cleans_up_disabled_version(self, tmp_path):
        """Test that add_node removes .disabled version before adding."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        # Create a .disabled directory
        disabled_dir = custom_nodes_dir / "test-node.disabled"
        disabled_dir.mkdir()
        (disabled_dir / "old_file.py").write_text("old content")

        # Create a cache directory for the node
        cache_dir = tmp_path / "cache" / "test-node"
        cache_dir.mkdir(parents=True)
        (cache_dir / "node.py").write_text("node content")

        mock_pyproject = Mock()
        mock_node_lookup = Mock()

        # Mock node info
        mock_node_info = NodeInfo(
            name="test-node",
            registry_id="test-node",
            source="registry"
        )

        mock_node_lookup.get_node.return_value = mock_node_info
        mock_node_lookup.download_to_cache.return_value = cache_dir
        mock_node_lookup.scan_requirements.return_value = []

        # Mock get_existing to return empty dict (no existing nodes)
        mock_pyproject.nodes.get_existing.return_value = {}

        node_manager = NodeManager(
            mock_pyproject, Mock(), mock_node_lookup, Mock(), custom_nodes_dir, Mock()
        )

        # Mock add_node_package to avoid full flow
        node_manager.add_node_package = Mock()

        # Call add_node
        node_manager.add_node("test-node", no_test=True)

        # Verify .disabled was removed
        assert not disabled_dir.exists()
        assert not (custom_nodes_dir / "test-node.disabled").exists()


class TestUpdateDevelopmentNode:
    """Tests for _update_development_node version tracking."""

    def test_update_dev_node_picks_up_new_version(self, tmp_path):
        """Dev node update should detect version change from node's pyproject.toml."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        # Create the node directory with a pyproject.toml containing new version
        node_dir = custom_nodes_dir / "test-node"
        node_dir.mkdir()
        (node_dir / "pyproject.toml").write_text(
            '[project]\nname = "test-node"\nversion = "0.0.18"\n'
        )

        mock_pyproject = Mock()
        mock_pyproject.nodes.generate_group_name.return_value = "test-node-abc123"
        mock_pyproject.dependencies.get_groups.return_value = {}

        node_info = NodeInfo(
            name="test-node",
            registry_id="test-node",
            version="0.0.16",
            source="development",
        )

        mock_node_lookup = Mock()
        mock_node_lookup.scan_requirements.return_value = []

        nm = NodeManager(
            mock_pyproject, Mock(), mock_node_lookup, Mock(), custom_nodes_dir, Mock()
        )

        result = nm._update_development_node("test-node", node_info, no_test=True)

        assert result.changed is True
        assert "version" in result.message
        assert node_info.version == "0.0.18"

    def test_update_dev_node_no_change_when_version_matches(self, tmp_path):
        """Dev node update should not report change when version is the same."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        node_dir = custom_nodes_dir / "test-node"
        node_dir.mkdir()
        (node_dir / "pyproject.toml").write_text(
            '[project]\nname = "test-node"\nversion = "1.0.0"\n'
        )

        mock_pyproject = Mock()
        mock_pyproject.nodes.generate_group_name.return_value = "test-node-abc123"
        mock_pyproject.dependencies.get_groups.return_value = {}

        node_info = NodeInfo(
            name="test-node",
            registry_id="test-node",
            version="1.0.0",
            source="development",
        )

        mock_node_lookup = Mock()
        mock_node_lookup.scan_requirements.return_value = []

        nm = NodeManager(
            mock_pyproject, Mock(), mock_node_lookup, Mock(), custom_nodes_dir, Mock()
        )

        result = nm._update_development_node("test-node", node_info, no_test=True)

        assert result.changed is False
        assert node_info.version == "1.0.0"


class TestInstallTransactionSafety:
    """Tests for install rollback and transaction safety (cg-ckh.1)."""

    def _make_node_manager(self, tmp_path):
        """Create a NodeManager with mocked dependencies for transaction tests."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        cache_dir = tmp_path / "cache" / "test-node"
        cache_dir.mkdir(parents=True)
        (cache_dir / "node.py").write_text("new node content")

        mock_pyproject = Mock()
        mock_pyproject.snapshot.return_value = {"snapshot": "data"}
        mock_pyproject.restore = Mock()
        mock_pyproject.nodes.get_existing.return_value = {}

        mock_uv = Mock()
        mock_node_lookup = Mock()
        mock_node_lookup.download_to_cache.return_value = cache_dir
        mock_node_lookup.scan_requirements.return_value = []

        node_manager = NodeManager(
            mock_pyproject, mock_uv, mock_node_lookup, Mock(), custom_nodes_dir, Mock()
        )
        node_manager.add_node_package = Mock()

        return node_manager, mock_pyproject, mock_uv, custom_nodes_dir, cache_dir

    def test_install_rollback_preserves_disabled_directory(self, tmp_path):
        """Bug 1: _install_node_from_info rollback must preserve .disabled backup.

        When .disabled exists and install fails, rollback should NOT have
        already deleted .disabled — it should still be available for recovery.
        """
        nm, mock_pyproject, mock_uv, custom_nodes_dir, _ = self._make_node_manager(tmp_path)

        # Create a pre-existing .disabled directory (from a previous update)
        disabled_dir = custom_nodes_dir / "test-node.disabled"
        disabled_dir.mkdir()
        (disabled_dir / "old_code.py").write_text("old version code")

        # Make uv sync fail to trigger rollback
        mock_uv.sync_project.side_effect = Exception("sync failed")

        node_info = NodeInfo(name="test-node", registry_id="test-node", source="registry")

        with pytest.raises((CDEnvironmentError, CDNodeConflictError)):
            nm._install_node_from_info(node_info, no_test=True)

        # .disabled MUST still exist after rollback
        assert disabled_dir.exists(), (
            ".disabled directory was deleted before install completed — "
            "rollback cannot restore old version"
        )
        assert (disabled_dir / "old_code.py").read_text() == "old version code"

    def test_install_rollback_resyncs_venv(self, tmp_path):
        """Bug 2: Install rollback must re-sync venv after restoring pyproject.

        After restoring pyproject.toml, the venv is out of sync. Rollback
        should attempt a best-effort re-sync.
        """
        nm, mock_pyproject, mock_uv, custom_nodes_dir, _ = self._make_node_manager(tmp_path)

        # Make sync fail on the FIRST call (during install), succeed on second (rollback re-sync)
        call_count = 0
        def sync_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("sync failed during install")

        mock_uv.sync_project.side_effect = sync_side_effect

        node_info = NodeInfo(name="test-node", registry_id="test-node", source="registry")

        with pytest.raises((CDEnvironmentError, CDNodeConflictError)):
            nm._install_node_from_info(node_info, no_test=True)

        # sync_project should have been called TWICE:
        # 1st: during install (fails) → triggers rollback
        # 2nd: during rollback re-sync (best-effort)
        assert mock_uv.sync_project.call_count >= 2, (
            f"Expected at least 2 sync_project calls (install + rollback re-sync), "
            f"got {mock_uv.sync_project.call_count}"
        )

    def test_add_node_replacement_restores_old_node_on_failure(self, tmp_path):
        """Bug 3: add_node version replacement must restore old node if install fails.

        When replacing an existing node with a different version, the old node
        should be moved to .disabled (not deleted) so it can be restored on failure.
        """
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        cache_dir = tmp_path / "cache" / "test-node"
        cache_dir.mkdir(parents=True)
        (cache_dir / "node.py").write_text("new version code")

        # Create the existing node directory
        old_node_dir = custom_nodes_dir / "TestNode"
        old_node_dir.mkdir()
        (old_node_dir / "node.py").write_text("old version code")

        mock_pyproject = Mock()
        mock_pyproject.snapshot.return_value = {"snapshot": "data"}
        mock_pyproject.restore = Mock()

        # Set up existing node in tracking
        existing_node = NodeInfo(
            name="TestNode", registry_id="test-node", version="1.0.0", source="registry"
        )
        mock_pyproject.nodes.get_existing.return_value = {"test-node": existing_node}

        mock_uv = Mock()
        mock_node_lookup = Mock()

        new_node_info = NodeInfo(
            name="TestNode", registry_id="test-node", version="2.0.0", source="registry"
        )
        mock_node_lookup.get_node.return_value = new_node_info
        mock_node_lookup.download_to_cache.return_value = cache_dir
        mock_node_lookup.scan_requirements.return_value = []

        mock_node_repo = Mock()
        mock_node_repo.resolve_github_url.return_value = None

        nm = NodeManager(
            mock_pyproject, mock_uv, mock_node_lookup, Mock(), custom_nodes_dir, mock_node_repo
        )
        nm.add_node_package = Mock()

        # Make sync succeed during remove_node (1st call), fail during new install (2nd call)
        call_count = 0
        def sync_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise Exception("sync failed on new version")

        mock_uv.sync_project.side_effect = sync_side_effect

        with pytest.raises((CDEnvironmentError, CDNodeConflictError)):
            nm.add_node("test-node@2.0.0", no_test=True)

        # Old node directory MUST be restored after failed replacement
        assert old_node_dir.exists(), (
            "Old node directory was permanently deleted during failed replacement — "
            "should have been restored from .disabled backup"
        )
        assert (old_node_dir / "node.py").read_text() == "old version code"

        # Pyproject must be restored to pre-replacement state (old node still tracked)
        mock_pyproject.restore.assert_called_once_with({"snapshot": "data"})
