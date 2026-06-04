"""Test status suggestion logic for different scenarios."""
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from comfygit_cli.env_commands import EnvironmentCommands
from comfygit_core.models import (
    DetailedWorkflowStatus,
    EnvironmentComparison,
    EnvironmentLifecycleStatus,
    EnvironmentStatus,
    GitStatus,
    LifecycleAction,
    LifecycleActionID,
    LifecycleIssue,
    WorkflowSyncStatus,
)


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


def _lifecycle_with_issue(action_id: str, issue_id: str) -> EnvironmentLifecycleStatus:
    lifecycle = _lifecycle(action_id)
    return EnvironmentLifecycleStatus(
        issues=(
            LifecycleIssue(
                id=issue_id,
                layer="filesystem",
                severity="warning",
                message="Development nodes declared by the manifest are missing locally.",
                affected_resources=("dev-node",),
                action_ids=(lifecycle.primary_action_id,),
            ),
        ),
        actions=lifecycle.actions,
        primary_action_id=lifecycle.primary_action_id,
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


def test_unresolved_workflow_model_suggestion_names_model_source_action(
    env_commands,
    mock_env,
    capsys,
):
    status = MagicMock()
    status.missing_models = []
    status.comparison.missing_nodes = []
    status.comparison.extra_nodes = []
    status.comparison.is_synced = True
    status.git.has_changes = False

    workflow = MagicMock(name="demo")
    workflow.name = "demo"
    workflow.resolution.models_unresolved = [MagicMock()]
    workflow.resolution.models_ambiguous = []
    status.workflow.analyzed_workflows = [workflow]
    status.workflow.workflows_with_issues = [workflow]

    with patch.object(env_commands, '_get_env', return_value=mock_env):
        env_commands._show_smart_suggestions(status, _lifecycle("add_model_source"))

    output = capsys.readouterr().out
    assert 'Add or select model source: cg workflow resolve "demo"' in output


def test_review_workflow_changes_suggests_commit_when_safe(
    env_commands,
    mock_env,
    capsys,
):
    status = MagicMock()
    status.workflow.sync_status.has_changes = True
    status.workflow.is_commit_safe = True

    with patch.object(env_commands, '_get_env', return_value=mock_env):
        env_commands._show_smart_suggestions(status, _lifecycle("review_workflow_changes"))

    output = capsys.readouterr().out
    assert 'Review workflow changes, then commit: cg commit -m "<message>"' in output


def test_missing_models_with_orphan_nodes(env_commands, mock_env, capsys):
    """Test suggestion when missing models + orphan nodes not in workflow.

    Scenario: Git pull adds nodes (some not in workflow) + model changes.
    Expected: Suggest 'sync' first, THEN 'workflow resolve'.
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

    # Should suggest sync first, then workflow resolve
    assert 'cg sync' in output
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
    Expected: Suggest 'sync' only.
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

    # Should only suggest sync
    assert 'cg sync' in output
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
    assert "Install missing nodes: cg sync" in output


def test_status_command_suggests_sync_for_package_drift(
    env_commands,
    mock_env,
    capsys,
):
    status = EnvironmentStatus(
        comparison=EnvironmentComparison(
            packages_in_sync=False,
            package_sync_message="Packages out of sync",
        ),
        git=GitStatus(has_changes=True, current_branch="main"),
        workflow=DetailedWorkflowStatus(sync_status=WorkflowSyncStatus()),
        missing_models=[],
    )
    lifecycle = _lifecycle("sync_environment")
    mock_env.status.return_value = status
    mock_env.get_lifecycle_status.return_value = lifecycle
    mock_env.get_manager_status.side_effect = RuntimeError("ignore manager notice")

    with patch.object(env_commands, "_get_env", return_value=mock_env):
        env_commands.status(MagicMock(verbose=False))

    output = capsys.readouterr().out
    assert "Environment needs sync" in output
    assert "Python packages out of sync" in output
    assert "Sync environment: cg sync" in output
    assert "Run: cg repair" not in output


def test_status_command_shows_lifecycle_suggestion_when_legacy_status_is_clean(
    env_commands,
    mock_env,
    capsys,
):
    status = EnvironmentStatus(
        comparison=EnvironmentComparison(dev_nodes_untracked=["dev-node"]),
        git=GitStatus(has_changes=False, current_branch="main"),
        workflow=DetailedWorkflowStatus(sync_status=WorkflowSyncStatus()),
        missing_models=[],
    )
    lifecycle = _lifecycle("track_dev_node")
    mock_env.status.return_value = status
    mock_env.get_lifecycle_status.return_value = lifecycle
    mock_env.get_manager_status.side_effect = RuntimeError("ignore manager notice")

    with patch.object(env_commands, "_get_env", return_value=mock_env):
        env_commands.status(MagicMock(verbose=False))

    output = capsys.readouterr().out
    assert "Environment: test-env (on main) ⚠️" in output
    assert "✓ No workflows" in output
    assert "Track development node: cg node add dev-node --dev" in output


def test_status_command_shows_unrendered_lifecycle_issue_details(
    env_commands,
    mock_env,
    capsys,
):
    status = EnvironmentStatus(
        comparison=EnvironmentComparison(dev_nodes_missing=["dev-node"]),
        git=GitStatus(has_changes=False, current_branch="main"),
        workflow=DetailedWorkflowStatus(sync_status=WorkflowSyncStatus()),
        missing_models=[],
    )
    lifecycle = _lifecycle_with_issue(
        "restore_or_relink_dev_node",
        "missing_development_nodes",
    )
    mock_env.status.return_value = status
    mock_env.get_lifecycle_status.return_value = lifecycle
    mock_env.get_manager_status.side_effect = RuntimeError("ignore manager notice")

    with patch.object(env_commands, "_get_env", return_value=mock_env):
        env_commands.status(MagicMock(verbose=False))

    output = capsys.readouterr().out
    assert "Environment needs attention" in output
    assert "Development nodes declared by the manifest are missing locally: dev-node" in output
    assert "Restore checkout: ComfyUI/custom_nodes/dev-node" in output
    assert "Or untrack it: cg node remove dev-node --dev --untrack" in output
