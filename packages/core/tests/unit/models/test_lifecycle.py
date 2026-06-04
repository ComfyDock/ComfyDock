"""Tests for public lifecycle status model shapes."""

from comfygit_core.models import (
    EnvironmentLifecycleStatus,
    LifecycleAction,
    LifecycleIssue,
    LifecycleLayerSummary,
)


def test_lifecycle_status_serializes_to_stable_adapter_shape():
    issue = LifecycleIssue(
        id="missing_declared_nodes",
        layer="filesystem",
        severity="error",
        message="Manifest declares nodes that are missing on disk.",
        blocking=True,
        affected_resources=("ComfyUI-Impact-Pack",),
        source="EnvironmentStatus.comparison.missing_nodes",
        action_ids=("sync_missing_nodes",),
    )
    action = LifecycleAction(
        id="sync_missing_nodes",
        label="Sync missing nodes",
        description="Install node folders declared by the manifest.",
        target_layer="filesystem",
        issue_ids=(issue.id,),
        expected_mutation_layers=("filesystem", "operation"),
        restart_required=True,
    )
    layer = LifecycleLayerSummary.from_issues("filesystem", (issue,))
    status = EnvironmentLifecycleStatus(
        environment_name="demo",
        workspace_path="/workspace",
        current_branch="main",
        current_commit="abc123",
        layers=(layer,),
        issues=(issue,),
        actions=(action,),
        primary_action_id=action.id,
    )

    assert status.primary_action == action
    assert status.to_dict() == {
        "environment_name": "demo",
        "workspace_path": "/workspace",
        "current_branch": "main",
        "current_commit": "abc123",
        "detached_head": False,
        "layers": [
            {
                "layer": "filesystem",
                "status": "blocked",
                "message": None,
                "issue_count": 1,
                "blocking_count": 1,
            },
        ],
        "issues": [
            {
                "id": "missing_declared_nodes",
                "layer": "filesystem",
                "severity": "error",
                "message": "Manifest declares nodes that are missing on disk.",
                "blocking": True,
                "affected_resources": ["ComfyUI-Impact-Pack"],
                "source": "EnvironmentStatus.comparison.missing_nodes",
                "details": [],
                "action_ids": ["sync_missing_nodes"],
            },
        ],
        "actions": [
            {
                "id": "sync_missing_nodes",
                "label": "Sync missing nodes",
                "description": "Install node folders declared by the manifest.",
                "target_layer": "filesystem",
                "issue_ids": ["missing_declared_nodes"],
                "expected_mutation_layers": ["filesystem", "operation"],
                "enabled": True,
                "disabled_reason": None,
                "destructive": False,
                "restart_required": True,
                "confirmation_required": False,
            },
        ],
        "primary_action_id": "sync_missing_nodes",
    }


def test_lifecycle_status_falls_back_to_first_enabled_action():
    disabled = LifecycleAction(
        id="commit_snapshot",
        label="Commit snapshot",
        description="Commit changes.",
        target_layer="snapshot",
        enabled=False,
        disabled_reason="Materialization blockers remain.",
    )
    enabled = LifecycleAction(
        id="sync_environment",
        label="Sync environment",
        description="Reconcile the manifest into the local filesystem.",
        target_layer="filesystem",
    )

    status = EnvironmentLifecycleStatus(actions=(disabled, enabled))

    assert status.primary_action == enabled


def test_lifecycle_layer_summary_distinguishes_ok_attention_and_blocked():
    assert LifecycleLayerSummary.from_issues("manifest", ()).status == "ok"

    warning = LifecycleIssue(
        id="untracked_node_folder",
        layer="filesystem",
        severity="warning",
        message="Node folder is not tracked.",
    )
    assert LifecycleLayerSummary.from_issues("filesystem", (warning,)).status == "attention"

    blocker = LifecycleIssue(
        id="workflow_unresolved_nodes",
        layer="manifest",
        severity="error",
        message="Workflow has unresolved nodes.",
        blocking=True,
    )
    assert LifecycleLayerSummary.from_issues("manifest", (blocker,)).status == "blocked"
