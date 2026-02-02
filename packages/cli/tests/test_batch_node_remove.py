"""Test batch node remove command functionality."""
from argparse import Namespace
from unittest.mock import MagicMock, patch

from comfygit_cli.env_commands import EnvironmentCommands


class TestBatchNodeRemove:
    """Test batch node remove command."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_single_node_uses_original_flow(self, mock_workspace):
        """Test that single node still uses original detailed result display."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env

        mock_result = MagicMock()
        mock_result.name = "test-node"
        mock_result.source = "registry"
        mock_result.filesystem_action = "deleted"
        mock_env.remove_node.return_value = mock_result
        mock_env.name = "test-env"

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args for single node
        args = Namespace(
            node_names=["test-node"],  # Single node
            dev=False,
            untrack=False,
            target_env=None
        )

        # Execute
        with patch('builtins.print'):
            cmd.node_remove(args)

        # Verify single node flow was used with default untrack_only=False
        mock_env.remove_node.assert_called_once_with("test-node", untrack_only=False)

        # Verify remove_nodes_with_progress was NOT called
        mock_env.remove_nodes_with_progress.assert_not_called()

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_multiple_nodes_uses_batch_flow(self, mock_workspace):
        """Test that multiple nodes trigger batch removal flow."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env
        mock_env.name = "test-env"

        # Mock batch removal
        mock_env.remove_nodes_with_progress.return_value = (2, [])  # 2 success, 0 failures

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args for multiple nodes
        args = Namespace(
            node_names=["node1", "node2"],  # Multiple nodes
            dev=False,
            target_env=None
        )

        # Execute
        with patch('builtins.print'):
            cmd.node_remove(args)

        # Verify batch flow was used
        mock_env.remove_nodes_with_progress.assert_called_once()
        call_args = mock_env.remove_nodes_with_progress.call_args

        # Verify node list
        assert call_args[0][0] == ["node1", "node2"]

        # Verify callbacks were provided
        assert call_args[1]['callbacks'] is not None

        # Verify remove_node was NOT called directly
        mock_env.remove_node.assert_not_called()

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_batch_handles_failures(self, mock_workspace):
        """Test that batch mode reports failures correctly."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env
        mock_env.name = "test-env"

        # Mock batch removal with failures
        mock_env.remove_nodes_with_progress.return_value = (
            1,  # 1 success
            [("node2", "Node not found")]  # 1 failure
        )

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args
        args = Namespace(
            node_names=["node1", "node2"],
            dev=False,
            target_env=None
        )

        # Execute
        with patch('builtins.print') as mock_print:
            cmd.node_remove(args)

        # Verify batch was called
        mock_env.remove_nodes_with_progress.assert_called_once()

        # Verify output mentions both success and failure
        print_calls = [str(call) for call in mock_print.call_args_list]
        output = " ".join(print_calls)

        assert "1/2" in output  # Success count
        assert "Failed to remove" in output  # Failure message
        assert "node2" in output  # Failed node name

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_batch_with_five_nodes(self, mock_workspace):
        """Test batch removal with five nodes (like user's example)."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.remove_nodes_with_progress.return_value = (5, [])  # All succeed

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args for five nodes (like user's example)
        args = Namespace(
            node_names=[
                "comfyui-depthanythingv2",
                "comfyui-basic-math",
                "comfyui-depthflow-nodes",
                "rgthree-comfy",
                "comfyui-videohelpersuite"
            ],
            dev=False,
            target_env=None
        )

        # Execute
        with patch('builtins.print'):
            cmd.node_remove(args)

        # Verify batch was called with all five nodes
        call_args = mock_env.remove_nodes_with_progress.call_args
        assert len(call_args[0][0]) == 5
        assert call_args[0][0] == args.node_names

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_untrack_flag_passes_to_remove_node(self, mock_workspace):
        """Test that --untrack flag is passed to remove_node."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env

        mock_result = MagicMock()
        mock_result.name = "test-node"
        mock_result.source = "development"
        mock_result.filesystem_action = "none"  # Untrack doesn't touch filesystem
        mock_env.remove_node.return_value = mock_result
        mock_env.name = "test-env"

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args with untrack flag
        args = Namespace(
            node_names=["test-node"],
            dev=False,
            untrack=True,  # The new flag
            target_env=None
        )

        # Execute
        with patch('builtins.print'):
            cmd.node_remove(args)

        # Verify remove_node was called with untrack_only=True
        mock_env.remove_node.assert_called_once_with("test-node", untrack_only=True)

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_untrack_flag_defaults_to_false(self, mock_workspace):
        """Test that untrack defaults to False for normal removal."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env

        mock_result = MagicMock()
        mock_result.name = "test-node"
        mock_result.source = "registry"
        mock_result.filesystem_action = "deleted"
        mock_env.remove_node.return_value = mock_result
        mock_env.name = "test-env"

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args without untrack flag
        args = Namespace(
            node_names=["test-node"],
            dev=False,
            untrack=False,
            target_env=None
        )

        # Execute
        with patch('builtins.print'):
            cmd.node_remove(args)

        # Verify remove_node was called with untrack_only=False
        mock_env.remove_node.assert_called_once_with("test-node", untrack_only=False)
