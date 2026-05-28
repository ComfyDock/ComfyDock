"""Tests for CLI error formatter."""

from comfygit_cli.formatters.error_formatter import NodeErrorFormatter
from comfygit_core.models import (
    CDNodeConflictError,
    NodeAction,
    NodeConflictContext,
)


def test_format_remove_node_action():
    """Test formatting of remove_node action."""
    action = NodeAction(
        action_type='remove_node',
        node_identifier='test-node',
        description='Remove the node'
    )

    result = NodeErrorFormatter.format_node_action(action)
    assert result == 'cg node remove test-node'


def test_format_add_node_dev_action():
    """Test formatting of add_node_dev action."""
    action = NodeAction(
        action_type='add_node_dev',
        node_name='my-node',
        description='Track as dev'
    )

    result = NodeErrorFormatter.format_node_action(action)
    assert result == 'cg node add my-node --dev'


def test_format_add_node_force_action():
    """Test formatting of add_node_force action."""
    action = NodeAction(
        action_type='add_node_force',
        node_identifier='registry-node',
        description='Force replace'
    )

    result = NodeErrorFormatter.format_node_action(action)
    assert result == 'cg node add registry-node --force'


def test_format_rename_directory_action():
    """Test formatting of rename_directory action."""
    action = NodeAction(
        action_type='rename_directory',
        directory_name='old-name',
        new_name='new-name',
        description='Rename directory'
    )

    result = NodeErrorFormatter.format_node_action(action)
    assert result == 'mv custom_nodes/old-name custom_nodes/new-name'


def test_format_update_node_action():
    """Test formatting of update_node action."""
    action = NodeAction(
        action_type='update_node',
        node_identifier='my-node',
        description='Update node'
    )

    result = NodeErrorFormatter.format_node_action(action)
    assert result == 'cg node update my-node'


def test_format_conflict_error_simple():
    """Test formatting a simple conflict error without context."""
    error = CDNodeConflictError("Simple error")

    result = NodeErrorFormatter.format_conflict_error(error)
    assert result == "Simple error"


def test_format_conflict_error_with_actions():
    """Test formatting a conflict error with suggested actions."""
    context = NodeConflictContext(
        conflict_type='directory_exists_non_git',
        node_name='my-node',
        suggested_actions=[
            NodeAction(
                action_type='add_node_dev',
                node_name='my-node',
                description='Track existing directory as development node'
            ),
            NodeAction(
                action_type='add_node_force',
                node_identifier='<identifier>',
                description='Force replace existing directory'
            )
        ]
    )

    error = CDNodeConflictError(
        "Directory 'my-node' already exists in custom_nodes/",
        context=context
    )

    result = NodeErrorFormatter.format_conflict_error(error)

    # Check that all parts are present
    assert "Directory 'my-node' already exists in custom_nodes/" in result
    assert "Suggested actions:" in result
    assert "1. Track existing directory as development node" in result
    assert "→ cg node add my-node --dev" in result
    assert "2. Force replace existing directory" in result
    assert "→ cg node add <identifier> --force" in result


def test_format_conflict_error_with_urls():
    """Test formatting a conflict error with repository URLs."""
    context = NodeConflictContext(
        conflict_type='different_repo_exists',
        node_name='ComfyUI-Manager',
        local_remote_url='https://github.com/user/fork',
        expected_remote_url='https://github.com/ltdrdata/ComfyUI-Manager',
        suggested_actions=[
            NodeAction(
                action_type='rename_directory',
                directory_name='ComfyUI-Manager',
                new_name='ComfyUI-Manager-fork',
                description='Rename your fork to avoid conflict'
            )
        ]
    )

    error = CDNodeConflictError(
        "Repository conflict for 'ComfyUI-Manager'",
        context=context
    )

    result = NodeErrorFormatter.format_conflict_error(error)

    # Check that URLs are displayed
    assert "Filesystem: https://github.com/user/fork" in result
    assert "Registry:   https://github.com/ltdrdata/ComfyUI-Manager" in result
    assert "Suggested actions:" in result
    assert "Rename your fork to avoid conflict" in result
    assert "mv custom_nodes/ComfyUI-Manager custom_nodes/ComfyUI-Manager-fork" in result


def test_format_conflict_error_multiline():
    """Test that formatted output is properly multiline."""
    context = NodeConflictContext(
        conflict_type='already_tracked',
        node_name='test-node',
        existing_identifier='old-test-node',
        suggested_actions=[
            NodeAction(
                action_type='remove_node',
                node_identifier='old-test-node',
                description='Remove existing node'
            )
        ]
    )

    error = CDNodeConflictError(
        "Node 'test-node' already exists",
        context=context
    )

    result = NodeErrorFormatter.format_conflict_error(error)
    lines = result.split('\n')

    # Should have multiple lines
    assert len(lines) >= 4  # Error + blank + header + action + command
    assert lines[0] == "Node 'test-node' already exists"
    assert "Suggested actions:" in result
