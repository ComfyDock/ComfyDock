"""Unit tests for lifecycle status decision policy."""

from comfygit_core.models import (
    EnvironmentComparison,
    EnvironmentStatus,
    GitStatus,
    LifecycleOperationState,
    LifecycleRuntimeState,
    ManifestModel,
    MissingModelInfo,
)
from comfygit_core.models.workflow import (
    DetailedWorkflowStatus,
    ResolvedModel,
    ResolutionResult,
    WorkflowAnalysisStatus,
    WorkflowDependencies,
    WorkflowNode,
    WorkflowNodeWidgetRef,
    WorkflowSyncStatus,
)
from comfygit_core.services.environment_lifecycle import (
    build_lifecycle_status_from_environment_status,
)


def _status(
    *,
    comparison: EnvironmentComparison | None = None,
    git: GitStatus | None = None,
    workflow: DetailedWorkflowStatus | None = None,
    missing_models: list[MissingModelInfo] | None = None,
) -> EnvironmentStatus:
    return EnvironmentStatus.create(
        comparison=comparison or EnvironmentComparison(),
        git_status=git or GitStatus(has_changes=False, current_branch="main"),
        workflow_status=workflow or DetailedWorkflowStatus(sync_status=WorkflowSyncStatus()),
        missing_models=missing_models,
    )


def test_missing_declared_nodes_blocks_commit_and_recommends_sync():
    status = _status(
        comparison=EnvironmentComparison(missing_nodes=["ComfyUI-Impact-Pack"]),
        git=GitStatus(has_changes=True, current_branch="main"),
    )

    lifecycle = build_lifecycle_status_from_environment_status(status)

    assert lifecycle.primary_action_id == "sync_missing_nodes"
    assert [issue.id for issue in lifecycle.issues] == [
        "missing_declared_nodes",
        "uncommitted_changes",
    ]
    assert lifecycle.layer("filesystem").status == "blocked"
    commit = next(action for action in lifecycle.actions if action.id == "commit_snapshot")
    assert commit.enabled is False
    assert commit.disabled_reason == "Resolve blocking lifecycle issues before committing."


def test_detached_head_outranks_materialization_blockers():
    status = _status(
        comparison=EnvironmentComparison(missing_nodes=["ComfyUI-Impact-Pack"]),
        git=GitStatus(has_changes=False, current_branch=None),
    )

    lifecycle = build_lifecycle_status_from_environment_status(status)

    assert lifecycle.primary_action_id == "create_branch"
    assert lifecycle.issues[0].id == "detached_head"
    assert lifecycle.layer("snapshot").status == "blocked"


def test_untracked_node_folder_recommends_review_not_blind_repair():
    status = _status(
        comparison=EnvironmentComparison(extra_nodes=["experimental-node"]),
    )

    lifecycle = build_lifecycle_status_from_environment_status(status)

    assert lifecycle.primary_action_id == "review_untracked_node"
    assert lifecycle.issues[0].id == "untracked_node_folder"
    assert lifecycle.issues[0].blocking is False
    assert lifecycle.actions[0].confirmation_required is True


def test_workflow_unresolved_nodes_recommend_resolution():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="synced",
                dependencies=WorkflowDependencies(workflow_name="demo"),
                resolution=ResolutionResult(
                    workflow_name="demo",
                    nodes_unresolved=[
                        WorkflowNode(id="1", type="MissingNode")
                    ],
                ),
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status)
    )

    assert lifecycle.primary_action_id == "resolve_workflow_nodes"
    assert lifecycle.issues[0].id == "workflow_unresolved_nodes"
    assert lifecycle.issues[0].affected_resources == ("demo",)


def test_missing_downloadable_model_recommends_download():
    missing = MissingModelInfo(
        model=ManifestModel(
            hash="abc123",
            filename="model.safetensors",
            size=1,
            relative_path="checkpoints/model.safetensors",
            category="checkpoints",
            sources=["https://example.com/model.safetensors"],
        ),
        workflow_names=["demo"],
        criticality="required",
        can_download=True,
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(missing_models=[missing])
    )

    assert lifecycle.primary_action_id == "download_required_models"
    assert lifecycle.issues[0].id == "missing_required_models"
    assert lifecycle.issues[0].blocking is True


def test_missing_model_without_source_recommends_source_selection():
    missing = MissingModelInfo(
        model=ManifestModel(
            hash="abc123",
            filename="model.safetensors",
            size=1,
            relative_path="checkpoints/model.safetensors",
            category="checkpoints",
        ),
        workflow_names=["demo"],
        criticality="required",
        can_download=False,
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(missing_models=[missing])
    )

    assert lifecycle.primary_action_id == "add_model_source"
    assert lifecycle.issues[0].id == "missing_required_models"


def test_runtime_restart_outranks_commit_when_supplied_by_adapter():
    status = _status(git=GitStatus(has_changes=True, current_branch="main"))

    lifecycle = build_lifecycle_status_from_environment_status(
        status,
        runtime_state=LifecycleRuntimeState(restart_required=True),
    )

    assert lifecycle.primary_action_id == "restart_comfyui"
    assert [issue.id for issue in lifecycle.issues] == [
        "runtime_restart_required",
        "uncommitted_changes",
    ]


def test_active_operation_outranks_everything_else():
    status = _status(
        comparison=EnvironmentComparison(missing_nodes=["ComfyUI-Impact-Pack"]),
        git=GitStatus(has_changes=True, current_branch=None),
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        status,
        operation_state=LifecycleOperationState(
            active=True,
            name="sync",
            message="Installing custom nodes",
        ),
    )

    assert lifecycle.primary_action_id == "view_operation_logs"
    assert lifecycle.issues[0].id == "operation_in_progress"


def test_model_path_sync_is_actionable_but_not_commit_blocking():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="synced",
                dependencies=WorkflowDependencies(workflow_name="demo"),
                resolution=ResolutionResult(
                    workflow_name="demo",
                    models_resolved=[
                        ResolvedModel(
                            workflow="demo",
                            reference=WorkflowNodeWidgetRef(
                                node_id="1",
                                node_type="CheckpointLoaderSimple",
                                widget_index=0,
                                widget_value="old-path/model.safetensors",
                            ),
                            needs_path_sync=True,
                        )
                    ],
                ),
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status)
    )

    assert lifecycle.primary_action_id == "sync_model_paths"
    assert lifecycle.issues[0].id == "model_path_mismatch"


def test_workflow_unresolved_model_refs_recommend_adding_source_or_local_model():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="synced",
                dependencies=WorkflowDependencies(workflow_name="demo"),
                resolution=ResolutionResult(
                    workflow_name="demo",
                    models_unresolved=[
                        WorkflowNodeWidgetRef(
                            node_id="1",
                            node_type="CheckpointLoaderSimple",
                            widget_index=0,
                            widget_value="missing.safetensors",
                        )
                    ],
                ),
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status)
    )

    assert lifecycle.primary_action_id == "add_model_source"
    assert lifecycle.issues[0].id == "missing_model_source"
