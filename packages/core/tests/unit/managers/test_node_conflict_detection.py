"""Tests for NodeManager git repo conflict detection."""

from unittest.mock import Mock, patch

from comfygit_core.managers.node_manager import NodeManager


class TestNodeConflictDetection:
    """Test git repository conflict detection."""

    def test_same_repository_https_urls(self):
        """Test URL normalization for HTTPS URLs."""
        assert NodeManager._same_repository(
            "https://github.com/owner/repo",
            "https://github.com/owner/repo"
        )
        assert NodeManager._same_repository(
            "https://github.com/owner/repo.git",
            "https://github.com/owner/repo"
        )
        assert NodeManager._same_repository(
            "https://github.com/owner/repo/",
            "https://github.com/owner/repo"
        )

    def test_same_repository_mixed_protocols(self):
        """Test URL normalization across different protocols."""
        assert NodeManager._same_repository(
            "git@github.com:owner/repo.git",
            "https://github.com/owner/repo"
        )
        assert NodeManager._same_repository(
            "ssh://git@github.com/owner/repo",
            "https://github.com/owner/repo"
        )

    def test_same_repository_case_insensitive(self):
        """Test URL comparison is case-insensitive."""
        assert NodeManager._same_repository(
            "https://github.com/Owner/Repo",
            "https://github.com/owner/repo"
        )

    def test_different_repositories(self):
        """Test detection of different repositories."""
        assert not NodeManager._same_repository(
            "https://github.com/owner1/repo",
            "https://github.com/owner2/repo"
        )
        assert not NodeManager._same_repository(
            "https://github.com/owner/repo1",
            "https://github.com/owner/repo2"
        )

    def test_check_filesystem_conflict_no_directory(self, tmp_path):
        """Test no conflict when directory doesn't exist."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        node_manager = NodeManager(
            Mock(), Mock(), Mock(), Mock(), custom_nodes_dir, Mock()
        )

        has_conflict, msg, context = node_manager._check_filesystem_conflict("test-node")
        assert not has_conflict
        assert msg == ""
        assert context is None

    def test_check_filesystem_conflict_regular_directory(self, tmp_path):
        """Test conflict detection for regular (non-git) directory."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        # Create regular directory
        node_dir = custom_nodes_dir / "test-node"
        node_dir.mkdir()

        node_manager = NodeManager(
            Mock(), Mock(), Mock(), Mock(), custom_nodes_dir, Mock()
        )

        has_conflict, msg, context = node_manager._check_filesystem_conflict("test-node")
        assert has_conflict
        assert "already exists" in msg
        assert context is not None
        assert context.conflict_type == 'directory_exists_non_git'
        assert len(context.suggested_actions) == 2

    @patch('comfygit_core.utils.git.git_remote_get_url')
    def test_check_filesystem_conflict_git_no_remote(self, mock_git_remote, tmp_path):
        """Test conflict detection for git repo with no remote."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        # Create git directory
        node_dir = custom_nodes_dir / "test-node"
        node_dir.mkdir()
        git_dir = node_dir / ".git"
        git_dir.mkdir()

        # Mock no remote
        mock_git_remote.return_value = None

        node_manager = NodeManager(
            Mock(), Mock(), Mock(), Mock(), custom_nodes_dir, Mock()
        )

        has_conflict, msg, context = node_manager._check_filesystem_conflict("test-node")
        assert has_conflict
        assert "no remote" in msg
        assert context is not None
        assert context.conflict_type == 'directory_exists_no_remote'

    @patch('comfygit_core.utils.git.git_remote_get_url')
    def test_check_filesystem_conflict_same_repo(self, mock_git_remote, tmp_path):
        """Test conflict detection when same repo already exists."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        # Create git directory
        node_dir = custom_nodes_dir / "test-node"
        node_dir.mkdir()
        git_dir = node_dir / ".git"
        git_dir.mkdir()

        # Mock remote URL
        mock_git_remote.return_value = "https://github.com/owner/test-node"

        node_manager = NodeManager(
            Mock(), Mock(), Mock(), Mock(), custom_nodes_dir, Mock()
        )

        has_conflict, msg, context = node_manager._check_filesystem_conflict(
            "test-node",
            expected_repo_url="https://github.com/owner/test-node.git"
        )
        assert has_conflict
        assert "already exists" in msg
        assert context is not None
        assert context.conflict_type == 'same_repo_exists'
        assert context.local_remote_url == "https://github.com/owner/test-node"

    @patch('comfygit_core.utils.git.git_remote_get_url')
    def test_check_filesystem_conflict_different_repo(self, mock_git_remote, tmp_path):
        """Test conflict detection for different repositories with same name."""
        custom_nodes_dir = tmp_path / "custom_nodes"
        custom_nodes_dir.mkdir()

        # Create git directory
        node_dir = custom_nodes_dir / "test-node"
        node_dir.mkdir()
        git_dir = node_dir / ".git"
        git_dir.mkdir()

        # Mock different remote URL
        mock_git_remote.return_value = "https://github.com/user/fork"

        node_manager = NodeManager(
            Mock(), Mock(), Mock(), Mock(), custom_nodes_dir, Mock()
        )

        has_conflict, msg, context = node_manager._check_filesystem_conflict(
            "test-node",
            expected_repo_url="https://github.com/owner/test-node"
        )
        assert has_conflict
        assert "conflict" in msg.lower()
        assert context is not None
        assert context.conflict_type == 'different_repo_exists'
        assert context.local_remote_url == "https://github.com/user/fork"
        assert context.expected_remote_url == "https://github.com/owner/test-node"
