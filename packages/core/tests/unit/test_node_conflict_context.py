"""Tests for NodeConflictContext and error formatting."""

from comfygit_core.models.exceptions import (
    CDNodeConflictError,
    NodeAction,
    NodeConflictContext,
)


def test_node_action_creation():
    """Test NodeAction dataclass creation."""
    action = NodeAction(
        action_type='remove_node',
        node_identifier='test-node',
        description='Remove the test node'
    )

    assert action.action_type == 'remove_node'
    assert action.node_identifier == 'test-node'
    assert action.description == 'Remove the test node'


def test_node_conflict_context_creation():
    """Test NodeConflictContext dataclass creation."""
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

    assert context.conflict_type == 'already_tracked'
    assert context.node_name == 'test-node'
    assert context.existing_identifier == 'old-test-node'
    assert len(context.suggested_actions) == 1
    assert context.suggested_actions[0].action_type == 'remove_node'


def test_node_conflict_error_with_context():
    """Test CDNodeConflictError with context."""
    context = NodeConflictContext(
        conflict_type='directory_exists_non_git',
        node_name='my-node',
        filesystem_path='/path/to/custom_nodes/my-node',
        suggested_actions=[
            NodeAction(
                action_type='add_node_dev',
                node_name='my-node',
                description='Track as dev node'
            ),
            NodeAction(
                action_type='add_node_force',
                node_identifier='<identifier>',
                description='Force replace'
            )
        ]
    )

    error = CDNodeConflictError(
        "Directory 'my-node' already exists",
        context=context
    )

    assert str(error) == "Directory 'my-node' already exists"
    assert error.context is not None
    assert error.context.conflict_type == 'directory_exists_non_git'

    actions = error.get_actions()
    assert len(actions) == 2
    assert actions[0].action_type == 'add_node_dev'
    assert actions[1].action_type == 'add_node_force'


def test_node_conflict_error_without_context():
    """Test CDNodeConflictError without context (backwards compat)."""
    error = CDNodeConflictError("Simple error message")

    assert str(error) == "Simple error message"
    assert error.context is None
    assert error.get_actions() == []


def test_repository_conflict_context():
    """Test repository conflict scenario."""
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
                description='Rename your fork'
            ),
            NodeAction(
                action_type='add_node_force',
                node_identifier='<identifier>',
                description='Replace with registry version'
            )
        ]
    )

    error = CDNodeConflictError(
        "Repository conflict for 'ComfyUI-Manager'",
        context=context
    )

    assert error.context.local_remote_url == 'https://github.com/user/fork'
    assert error.context.expected_remote_url == 'https://github.com/ltdrdata/ComfyUI-Manager'

    actions = error.get_actions()
    assert len(actions) == 2
    assert actions[0].action_type == 'rename_directory'
    assert actions[0].new_name == 'ComfyUI-Manager-fork'
