"""Test status suggestion logic for different scenarios."""
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from comfygit_cli.env_commands import EnvironmentCommands
from comfygit_core.models import (
    EnvironmentComparison,
    EnvironmentLifecycleStatus,
    EnvironmentStatus,
    GitStatus,
    LifecycleAction,
    LifecycleActionID,
    WorkflowSyncStatus,
)
from comfygit_core.models.workflow import DetailedWorkflowStatus


@pytest.fixture
def env_commands():
    """Create EnvironmentCommands instance."""
    return EnvironmentCommands()


@pytest.fixture
def mock_env():
    """Create mock environment."""
    env = MagicMock()
    env.name = "test-env"
    return env


def _lifecycle(action_id: str) -> EnvironmentLifecycleStatus:
    typed_action_id = cast(LifecycleActionID, action_id)
    return EnvironmentLifecycleStatus(
        actions=(
            LifecycleAction(
                id=typed_action_id,
                label=action_id.replace("_", " ").title(),
                description=f"{action_id} action",
                target_layer="filesystem",
            ),
        ),
        primary_action_id=typed_action_id,
    )


def test_missing_models_with_workflow_nodes_only(env_commands, mock_env, capsys):
    """Test suggestion when missing models + all missing nodes are workflow-related.

    Scenario: Git pull adds nodes used by workflow + model changes.
    Expected: Suggest 'workflow resolve' (handles both models and nodes).
    """
    # Setup: 2 missing nodes, both referenced by workflow
    mock_env.get_uninstalled_nodes.return_value = ['rgthree-comfy', 'comfyui-akatz-nodes']

    # Mock status with missing models and missing nodes
    status = MagicMock()
    status.missing_models = [
        MagicMock(workflow_names=['default'], model=MagicMock(filename='model.safetensors'))
    ]
    status.comparison.missing_nodes = ['rgthree-comfy', 'comfyui-akatz-nodes']
    status.comparison.extra_nodes = []
    status.comparison.is_synced = False

    # Mock workflow with uninstalled_nodes matching missing_nodes
    mock_wf = MagicMock(name='default')
    mock_wf.uninstalled_nodes = ['rgthree-comfy', 'comfyui-akatz-nodes']
    status.workflow.analyzed_workflows = [mock_wf]
    status.workflow.workflows_with_issues = []

    # Mock _get_env to return our mock
    with patch.object(env_commands, '_get_env', return_value=mock_env):
        env_commands._show_smart_suggestions(status, _lifecycle("add_model_source"))

    output = capsys.readouterr().out

    # Should suggest workflow resolve (not repair first)
    assert 'workflow resolve "default"' in output
    assert 'cg repair' not in output


def test_missing_models_with_orphan_nodes(env_commands, mock_env, capsys):
    """Test suggestion when missing models + orphan nodes not in workflow.

    Scenario: Git pull adds nodes (some not in workflow) + model changes.
    Expected: Suggest 'repair' first, THEN 'workflow resolve'.
    """
    # Setup: 2 missing nodes, only 1 referenced by workflow
    mock_env.get_uninstalled_nodes.return_value = ['rgthree-comfy']

    # Mock status with missing models and orphan nodes
    status = MagicMock()
    status.missing_models = [
        MagicMock(workflow_names=['default'], model=MagicMock(filename='model.safetensors'))
    ]
    status.comparison.missing_nodes = ['rgthree-comfy', 'some-other-node']  # orphan: some-other-node
    status.comparison.extra_nodes = []
    status.comparison.is_synced = False
    status.workflow.analyzed_workflows = [MagicMock(name='default')]
    status.workflow.workflows_with_issues = []

    with patch.object(env_commands, '_get_env', return_value=mock_env):
        env_commands._show_smart_suggestions(status, _lifecycle("sync_missing_nodes"))

    output = capsys.readouterr().out

    # Should suggest repair first, then workflow resolve
    assert 'cg repair' in output
    assert 'Then resolve workflow: cg workflow resolve "default"' in output


def test_missing_models_with_extra_nodes(env_commands, mock_env, capsys):
    """Test suggestion when missing models + extra nodes on filesystem.

    Scenario: Git pull with model changes, but user has untracked nodes.
    Expected: Suggest 'repair' first (to remove extra), THEN 'workflow resolve'.
    """
    # Setup: No uninstalled workflow nodes
    mock_env.get_uninstalled_nodes.return_value = []

    # Mock status with missing models and extra nodes
    status = MagicMock()
    status.missing_models = [
        MagicMock(workflow_names=['default'], model=MagicMock(filename='model.safetensors'))
    ]
    status.comparison.missing_nodes = []
    status.comparison.extra_nodes = ['old-node-1', 'old-node-2']
    status.comparison.is_synced = False
    status.workflow.analyzed_workflows = [MagicMock(name='default')]
    status.workflow.workflows_with_issues = []

    with patch.object(env_commands, '_get_env', return_value=mock_env):
        env_commands._show_smart_suggestions(status, _lifecycle("review_untracked_node"))

    output = capsys.readouterr().out

    # Should suggest repair first (to remove extra nodes), then workflow resolve
    assert 'cg repair' in output
    assert 'Then resolve workflow: cg workflow resolve "default"' in output


def test_environment_drift_only(env_commands, mock_env, capsys):
    """Test suggestion when only environment drift (no workflow issues).

    Scenario: Missing/extra nodes but no workflow issues.
    Expected: Suggest 'repair' only.
    """
    mock_env.get_uninstalled_nodes.return_value = []

    # Mock status with environment drift but no missing models
    status = MagicMock()
    status.missing_models = []
    status.comparison.missing_nodes = ['some-node']
    status.comparison.extra_nodes = []
    status.comparison.is_synced = False
    status.workflow.analyzed_workflows = []
    status.workflow.workflows_with_issues = []

    with patch.object(env_commands, '_get_env', return_value=mock_env):
        env_commands._show_smart_suggestions(status, _lifecycle("sync_missing_nodes"))

    output = capsys.readouterr().out

    # Should only suggest repair
    assert 'cg repair' in output
    assert 'workflow resolve' not in output


def test_status_command_uses_environment_lifecycle_facade(env_commands, mock_env, capsys):
    status = EnvironmentStatus(
        comparison=EnvironmentComparison(missing_nodes=["some-node"]),
        git=GitStatus(has_changes=False, current_branch="main"),
        workflow=DetailedWorkflowStatus(sync_status=WorkflowSyncStatus()),
        missing_models=[],
    )
    lifecycle = _lifecycle("sync_missing_nodes")
    mock_env.status.return_value = status
    mock_env.get_lifecycle_status.return_value = lifecycle
    mock_env.get_manager_status.side_effect = RuntimeError("ignore manager notice")

    with patch.object(env_commands, "_get_env", return_value=mock_env):
        env_commands.status(MagicMock(verbose=False))

    mock_env.get_lifecycle_status.assert_called_once_with(status=status)
    output = capsys.readouterr().out
    assert "Install missing nodes: cg repair" in output
