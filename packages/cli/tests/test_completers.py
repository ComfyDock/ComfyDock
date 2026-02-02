"""Tests for argcomplete completers."""
from argparse import Namespace
from unittest.mock import Mock, patch

from comfygit_cli.completers import (
    branch_completer,
    commit_hash_completer,
    environment_completer,
    filter_by_prefix,
    get_env_from_args,
    get_workspace_safe,
    installed_node_completer,
    ref_completer,
    workflow_completer,
)
from comfygit_core.models.exceptions import CDWorkspaceNotFoundError
from comfygit_core.models.workflow import WorkflowSyncStatus


class TestSharedUtilities:
    """Test shared utility functions."""

    def test_filter_by_prefix(self):
        """Test filtering items by prefix."""
        items = ["apple", "application", "banana", "apply"]
        result = filter_by_prefix(items, "app")
        assert result == ["apple", "application", "apply"]

    def test_filter_by_prefix_empty(self):
        """Test filtering with empty prefix returns all items."""
        items = ["apple", "banana", "cherry"]
        result = filter_by_prefix(items, "")
        assert result == items

    def test_filter_by_prefix_no_matches(self):
        """Test filtering with no matches."""
        items = ["apple", "banana", "cherry"]
        result = filter_by_prefix(items, "xyz")
        assert result == []

    @patch('comfygit_cli.completers.WorkspaceFactory.find')
    def test_get_workspace_safe_success(self, mock_find):
        """Test getting workspace successfully."""
        mock_workspace = Mock()
        mock_find.return_value = mock_workspace

        result = get_workspace_safe()
        assert result == mock_workspace

    @patch('comfygit_cli.completers.WorkspaceFactory.find')
    def test_get_workspace_safe_not_found(self, mock_find):
        """Test get_workspace_safe returns None when not found."""
        mock_find.side_effect = CDWorkspaceNotFoundError("Not found")

        result = get_workspace_safe()
        assert result is None

    def test_get_env_from_args_with_target_env(self):
        """Test getting environment from -e flag."""
        mock_workspace = Mock()
        mock_env = Mock()
        mock_workspace.get_environment.return_value = mock_env

        parsed_args = Namespace(target_env="test-env")
        result = get_env_from_args(parsed_args, mock_workspace)

        assert result == mock_env
        mock_workspace.get_environment.assert_called_once_with("test-env", auto_sync=False)

    def test_get_env_from_args_active_env(self):
        """Test getting active environment when no -e flag."""
        mock_workspace = Mock()
        mock_env = Mock()
        mock_workspace.get_active_environment.return_value = mock_env

        parsed_args = Namespace()
        result = get_env_from_args(parsed_args, mock_workspace)

        assert result == mock_env
        mock_workspace.get_active_environment.assert_called_once()


class TestEnvironmentCompleter:
    """Test environment_completer function."""

    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_complete_environment_names(self, mock_get_workspace):
        """Test completing environment names."""
        # Setup mock environments
        mock_env1 = Mock()
        mock_env1.name = "stable"
        mock_env2 = Mock()
        mock_env2.name = "testing"
        mock_env3 = Mock()
        mock_env3.name = "experimental"

        mock_workspace = Mock()
        mock_workspace.list_environments.return_value = [mock_env1, mock_env2, mock_env3]
        mock_get_workspace.return_value = mock_workspace

        # Test completion
        result = environment_completer("test", Mock())
        assert result == ["testing"]

    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_complete_all_environments(self, mock_get_workspace):
        """Test completing with empty prefix returns all environments."""
        mock_env1 = Mock()
        mock_env1.name = "stable"
        mock_env2 = Mock()
        mock_env2.name = "testing"

        mock_workspace = Mock()
        mock_workspace.list_environments.return_value = [mock_env1, mock_env2]
        mock_get_workspace.return_value = mock_workspace

        result = environment_completer("", Mock())
        assert result == ["stable", "testing"]

    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_no_workspace_returns_empty(self, mock_get_workspace):
        """Test returns empty list when no workspace."""
        mock_get_workspace.return_value = None

        result = environment_completer("", Mock())
        assert result == []


class TestWorkflowCompleter:
    """Test workflow_completer function."""

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_complete_workflow_names(self, mock_get_workspace, mock_get_env):
        """Test completing workflow names."""
        # Setup mocks
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace

        mock_env = Mock()
        workflows = WorkflowSyncStatus(
            new=["workflow1.json"],
            modified=["workflow2.json"],
            synced=["workflow3.json"],
            deleted=[]
        )
        mock_env.list_workflows.return_value = workflows
        mock_get_env.return_value = mock_env

        # Test completion
        result = workflow_completer("work", Mock())
        assert result == ["workflow1", "workflow2", "workflow3"]

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_workflow_priority_ordering(self, mock_get_workspace, mock_get_env):
        """Test workflows are ordered with new/modified first."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace

        mock_env = Mock()
        workflows = WorkflowSyncStatus(
            new=["new-workflow.json"],
            modified=["modified-workflow.json"],
            synced=["synced-workflow.json"],
            deleted=[]
        )
        mock_env.list_workflows.return_value = workflows
        mock_get_env.return_value = mock_env

        result = workflow_completer("", Mock())
        # Check order: new first, then modified, then synced
        assert result == ["new-workflow", "modified-workflow", "synced-workflow"]

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_no_environment_returns_empty(self, mock_get_workspace, mock_get_env):
        """Test returns empty list when no environment."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace
        mock_get_env.return_value = None

        result = workflow_completer("", Mock())
        assert result == []


class TestInstalledNodeCompleter:
    """Test installed_node_completer function."""

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_complete_installed_nodes(self, mock_get_workspace, mock_get_env):
        """Test completing installed node names."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace

        mock_env = Mock()
        # Create mock nodes with registry_id
        node1 = Mock()
        node1.registry_id = "comfyui-manager"
        node1.name = "ComfyUI-Manager"

        node2 = Mock()
        node2.registry_id = "animatediff"
        node2.name = "AnimateDiff"

        node3 = Mock()
        node3.registry_id = None
        node3.name = "custom-node"

        mock_env.list_nodes.return_value = [node1, node2, node3]
        mock_get_env.return_value = mock_env

        result = installed_node_completer("", Mock())
        assert result == ["comfyui-manager", "animatediff", "custom-node"]

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_complete_with_prefix(self, mock_get_workspace, mock_get_env):
        """Test completing nodes with prefix filter."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace

        mock_env = Mock()
        node1 = Mock()
        node1.registry_id = "comfyui-manager"
        node1.name = "ComfyUI-Manager"

        node2 = Mock()
        node2.registry_id = "comfyui-inspire-pack"
        node2.name = "ComfyUI-Inspire-Pack"

        node3 = Mock()
        node3.registry_id = "animatediff"
        node3.name = "AnimateDiff"

        mock_env.list_nodes.return_value = [node1, node2, node3]
        mock_get_env.return_value = mock_env

        result = installed_node_completer("comfyui", Mock())
        assert result == ["comfyui-manager", "comfyui-inspire-pack"]

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_no_environment_returns_empty(self, mock_get_workspace, mock_get_env):
        """Test returns empty list when no environment."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace
        mock_get_env.return_value = None

        result = installed_node_completer("", Mock())
        assert result == []


class TestCommitHashCompleter:
    """Test commit_hash_completer function."""

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_returns_only_hashes_not_messages(self, mock_get_workspace, mock_get_env):
        """Test that completion returns only commit hashes, not messages."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace

        mock_env = Mock()
        # Simulate commit history with hash and message
        mock_env.get_commit_history.return_value = [
            {'hash': '7725f89', 'message': '3 models queued for download'},
            {'hash': '5439eb6', 'message': '1 models not found, 2 models queued'},
            {'hash': '9090f70', 'message': 'Initial environment setup'},
        ]
        mock_get_env.return_value = mock_env

        result = commit_hash_completer("", Mock())

        # Should return ONLY hashes, not "hash (message)" format
        assert result == ['7725f89', '5439eb6', '9090f70']
        # Verify no commit messages or parentheses in results
        for item in result:
            assert '(' not in item
            assert ')' not in item
            assert len(item) == 7  # Short hash length

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_filters_by_prefix(self, mock_get_workspace, mock_get_env):
        """Test that completion filters hashes by prefix."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace

        mock_env = Mock()
        mock_env.get_commit_history.return_value = [
            {'hash': '7725f89', 'message': 'Some message'},
            {'hash': '5439eb6', 'message': 'Another message'},
            {'hash': '9090f70', 'message': 'Third message'},
        ]
        mock_get_env.return_value = mock_env

        result = commit_hash_completer("54", Mock())

        # Should return only the hash starting with "54"
        assert result == ['5439eb6']

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_no_environment_returns_empty(self, mock_get_workspace, mock_get_env):
        """Test returns empty list when no environment."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace
        mock_get_env.return_value = None

        result = commit_hash_completer("", Mock())
        assert result == []


class TestBranchCompleter:
    """Test branch_completer function."""

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_returns_branch_names(self, mock_get_workspace, mock_get_env):
        """Test that completion returns branch names."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace

        mock_env = Mock()
        # list_branches returns list of (name, is_current) tuples
        mock_env.list_branches.return_value = [
            ('main', True),
            ('feature-x', False),
            ('bugfix-123', False),
        ]
        mock_get_env.return_value = mock_env

        result = branch_completer("", Mock())

        # Should return only branch names
        assert result == ['main', 'feature-x', 'bugfix-123']

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_filters_by_prefix(self, mock_get_workspace, mock_get_env):
        """Test that completion filters branches by prefix."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace

        mock_env = Mock()
        mock_env.list_branches.return_value = [
            ('main', True),
            ('feature-x', False),
            ('feature-y', False),
            ('bugfix-123', False),
        ]
        mock_get_env.return_value = mock_env

        result = branch_completer("feat", Mock())

        # Should return only branches starting with "feat"
        assert result == ['feature-x', 'feature-y']

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_no_environment_returns_empty(self, mock_get_workspace, mock_get_env):
        """Test returns empty list when no environment."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace
        mock_get_env.return_value = None

        result = branch_completer("", Mock())
        assert result == []


class TestRefCompleter:
    """Test ref_completer function (branches + commits)."""

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_returns_branches_and_commits(self, mock_get_workspace, mock_get_env):
        """Test that completion returns both branches and commits."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace

        mock_env = Mock()
        # Branches
        mock_env.list_branches.return_value = [
            ('main', True),
            ('feature-x', False),
        ]
        # Commits
        mock_env.get_commit_history.return_value = [
            {'hash': '7725f89', 'message': 'Recent commit'},
            {'hash': '5439eb6', 'message': 'Older commit'},
        ]
        mock_get_env.return_value = mock_env

        result = ref_completer("", Mock())

        # Should return branches first, then commits
        assert result == ['main', 'feature-x', '7725f89', '5439eb6']

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_filters_branches_and_commits_by_prefix(self, mock_get_workspace, mock_get_env):
        """Test that completion filters both branches and commits."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace

        mock_env = Mock()
        mock_env.list_branches.return_value = [
            ('main', True),
            ('feature-x', False),
        ]
        mock_env.get_commit_history.return_value = [
            {'hash': '7725f89', 'message': 'Recent commit'},
            {'hash': '5439eb6', 'message': 'Older commit'},
        ]
        mock_get_env.return_value = mock_env

        # Filter for refs starting with 'f'
        result = ref_completer("f", Mock())
        assert result == ['feature-x']

        # Filter for refs starting with '7'
        result = ref_completer("7", Mock())
        assert result == ['7725f89']

    @patch('comfygit_cli.completers.get_env_from_args')
    @patch('comfygit_cli.completers.get_workspace_safe')
    def test_no_environment_returns_empty(self, mock_get_workspace, mock_get_env):
        """Test returns empty list when no environment."""
        mock_workspace = Mock()
        mock_get_workspace.return_value = mock_workspace
        mock_get_env.return_value = None

        result = ref_completer("", Mock())
        assert result == []
