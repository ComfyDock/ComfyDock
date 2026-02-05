"""Test batch node add command functionality."""
from argparse import Namespace
from unittest.mock import MagicMock, patch

from comfygit_cli.env_commands import EnvironmentCommands


class TestBatchNodeAdd:
    """Test batch node add command."""

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_single_node_uses_original_flow(self, mock_workspace):
        """Test that single node still uses original detailed error handling."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env

        mock_node_info = MagicMock()
        mock_node_info.name = "test-node"
        mock_env.add_node.return_value = mock_node_info
        mock_env.name = "test-env"

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args for single node
        args = Namespace(
            node_names=["test-node"],  # Single node
            dev=False,
            no_test=False,
            force=False,
            target_env=None
        )

        # Execute
        with patch('builtins.print'):
            cmd.node_add(args)

        # Verify single node flow was used (add_node called, not batch)
        mock_env.add_node.assert_called_once()
        call_kwargs = mock_env.add_node.call_args.kwargs

        # Verify essential parameters
        assert mock_env.add_node.call_args.args[0] == "test-node"
        assert call_kwargs['is_development'] is False
        assert call_kwargs['no_test'] is False
        assert call_kwargs['force'] is False

        # Verify install_nodes_with_progress was NOT called
        mock_env.install_nodes_with_progress.assert_not_called()

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_single_node_passes_extras(self, mock_workspace):
        """Test that extras flags are passed to add_node."""
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env

        mock_node_info = MagicMock()
        mock_node_info.name = "test-node"
        mock_env.add_node.return_value = mock_node_info
        mock_env.name = "test-env"

        cmd = EnvironmentCommands()

        args = Namespace(
            node_names=["test-node"],
            dev=False,
            no_test=False,
            force=False,
            target_env=None,
            extra=["cuda"],
            all_extras=False,
        )

        with patch('builtins.print'):
            cmd.node_add(args)

        call_kwargs = mock_env.add_node.call_args.kwargs
        assert call_kwargs["extras"] == ["cuda"]
        assert call_kwargs["all_extras"] is False

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_multiple_nodes_uses_batch_flow(self, mock_workspace):
        """Test that multiple nodes trigger batch installation flow."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env
        mock_env.name = "test-env"

        # Mock batch installation
        mock_env.install_nodes_with_progress.return_value = (2, [])  # 2 success, 0 failures

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args for multiple nodes
        args = Namespace(
            node_names=["node1", "node2"],  # Multiple nodes
            dev=False,
            no_test=False,
            force=False,
            target_env=None
        )

        # Execute
        with patch('builtins.print'):
            cmd.node_add(args)

        # Verify batch flow was used
        mock_env.install_nodes_with_progress.assert_called_once()
        call_args = mock_env.install_nodes_with_progress.call_args

        # Verify node list
        assert call_args[0][0] == ["node1", "node2"]

        # Verify callbacks were provided
        assert call_args[1]['callbacks'] is not None

        # Verify add_node was NOT called directly
        mock_env.add_node.assert_not_called()

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_batch_handles_failures(self, mock_workspace):
        """Test that batch mode reports failures correctly."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env
        mock_env.name = "test-env"

        # Mock batch installation with failures
        mock_env.install_nodes_with_progress.return_value = (
            1,  # 1 success
            [("node2", "Node not found")]  # 1 failure
        )

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args
        args = Namespace(
            node_names=["node1", "node2"],
            dev=False,
            no_test=False,
            force=False,
            target_env=None
        )

        # Execute
        with patch('builtins.print') as mock_print:
            cmd.node_add(args)

        # Verify batch was called
        mock_env.install_nodes_with_progress.assert_called_once()

        # Verify output mentions both success and failure
        print_calls = [str(call) for call in mock_print.call_args_list]
        output = " ".join(print_calls)

        assert "1/2" in output  # Success count
        assert "Failed to install" in output  # Failure message
        assert "node2" in output  # Failed node name

    @patch('comfygit_cli.env_commands.get_workspace_or_exit')
    def test_batch_with_three_nodes(self, mock_workspace):
        """Test batch installation with three nodes."""
        # Setup mocks
        mock_env = MagicMock()
        mock_workspace.return_value.get_active_environment.return_value = mock_env
        mock_workspace.return_value.get_environment.return_value = mock_env
        mock_env.name = "test-env"
        mock_env.install_nodes_with_progress.return_value = (3, [])  # All succeed

        # Create command handler
        cmd = EnvironmentCommands()

        # Create args for three nodes
        args = Namespace(
            node_names=["node1", "node2", "node3"],
            dev=False,
            no_test=False,
            force=False,
            target_env=None
        )

        # Execute
        with patch('builtins.print'):
            cmd.node_add(args)

        # Verify batch was called with all three nodes
        call_args = mock_env.install_nodes_with_progress.call_args
        assert call_args[0][0] == ["node1", "node2", "node3"]
