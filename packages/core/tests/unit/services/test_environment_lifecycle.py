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
    ResolutionResult,
    ResolvedModel,
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


def test_missing_development_node_recommends_restore_or_untrack_not_repair():
    status = _status(
        comparison=EnvironmentComparison(dev_nodes_missing=["dev-node"]),
    )

    lifecycle = build_lifecycle_status_from_environment_status(status)

    assert lifecycle.primary_action_id == "restore_or_relink_dev_node"
    assert lifecycle.issues[0].id == "missing_development_nodes"


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


def test_workflow_uninstalled_nodes_use_node_materialization_wording():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(synced=["demo"]),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="synced",
                dependencies=WorkflowDependencies(workflow_name="demo"),
                resolution=ResolutionResult(workflow_name="demo"),
                uninstalled_nodes=["ComfyUI-Impact-Pack"],
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(
            comparison=EnvironmentComparison(missing_nodes=["ComfyUI-Impact-Pack"]),
            workflow=workflow_status,
        )
    )

    assert lifecycle.primary_action_id == "sync_missing_nodes"
    issue = next(
        issue for issue in lifecycle.issues if issue.id == "workflow_uninstalled_nodes"
    )
    assert issue.message == "Tracked workflow nodes are not installed locally."
    assert issue.affected_resources == ("demo",)


def test_synced_workflow_with_untracked_uninstalled_nodes_recommends_resolution():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(synced=["demo"]),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="synced",
                dependencies=WorkflowDependencies(workflow_name="demo"),
                resolution=ResolutionResult(workflow_name="demo"),
                uninstalled_nodes=["ComfyUI-Impact-Pack"],
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status)
    )

    assert lifecycle.primary_action_id == "resolve_workflow_nodes"
    assert lifecycle.issues[0].id == "workflow_node_dependencies_pending"
    assert lifecycle.issues[0].message == (
        "Workflows need custom-node dependencies resolved before they can be installed."
    )
    assert lifecycle.issues[0].affected_resources == ("demo",)


def test_new_workflow_with_uninstalled_nodes_recommends_resolution_before_sync():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(new=["demo"]),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="new",
                dependencies=WorkflowDependencies(workflow_name="demo"),
                resolution=ResolutionResult(workflow_name="demo"),
                uninstalled_nodes=["ComfyUI-Impact-Pack"],
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status)
    )

    assert lifecycle.primary_action_id == "resolve_workflow_nodes"
    assert lifecycle.issues[0].id == "workflow_node_dependencies_pending"
    assert lifecycle.issues[0].message == (
        "Workflows need custom-node dependencies resolved before they can be installed."
    )
    assert lifecycle.issues[0].affected_resources == ("demo",)


def test_new_workflow_with_unresolved_nodes_recommends_resolution_before_sync():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(new=["demo"]),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="new",
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
    assert [action.id for action in lifecycle.actions][:2] == [
        "resolve_workflow_nodes",
        "commit_snapshot",
    ]


def test_new_workflow_without_dependency_issues_recommends_commit_snapshot():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(new=["demo"]),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="new",
                dependencies=WorkflowDependencies(workflow_name="demo"),
                resolution=ResolutionResult(workflow_name="demo"),
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status)
    )

    assert lifecycle.primary_action_id == "commit_snapshot"
    assert lifecycle.issues[0].id == "new_workflow_added"
    assert lifecycle.issues[0].layer == "snapshot"
    assert lifecycle.issues[0].affected_resources == ("demo",)


def test_sync_preview_preserves_uncommitted_workflows_by_default():
    status = _status(
        workflow=DetailedWorkflowStatus(
            sync_status=WorkflowSyncStatus(new=["draft"], modified=["edited"]),
        )
    )

    safe_preview = status.get_sync_preview()
    assert safe_preview["workflows_to_preserve"] == ["draft", "edited"]
    assert safe_preview["workflows_to_remove"] == []
    assert safe_preview["workflows_to_update"] == []

    restore_preview = status.get_sync_preview(preserve_workflows=False)
    assert restore_preview["workflows_to_preserve"] == []
    assert restore_preview["workflows_to_remove"] == ["draft"]
    assert restore_preview["workflows_to_update"] == ["edited"]


def test_modified_workflow_without_dependency_issues_recommends_commit_snapshot():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(modified=["demo"]),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="modified",
                dependencies=WorkflowDependencies(workflow_name="demo"),
                resolution=ResolutionResult(workflow_name="demo"),
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status)
    )

    assert lifecycle.primary_action_id == "commit_snapshot"
    assert lifecycle.issues[0].id == "workflow_modified"
    assert lifecycle.issues[0].layer == "snapshot"
    assert lifecycle.issues[0].message.startswith("Workflow modified")
    assert [action.id for action in lifecycle.actions[:2]] == [
        "commit_snapshot",
        "review_workflow_changes",
    ]


def test_deleted_workflow_without_dependency_issues_recommends_commit_snapshot():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(deleted=["old_demo"]),
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status)
    )

    assert lifecycle.primary_action_id == "commit_snapshot"
    assert lifecycle.issues[0].id == "workflow_deleted"
    assert lifecycle.issues[0].message.startswith("Workflow removed")


def test_mixed_workflow_changes_recommend_commit_snapshot():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(
            new=["new_demo"],
            modified=["changed_demo"],
        ),
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status)
    )

    assert lifecycle.primary_action_id == "commit_snapshot"
    assert lifecycle.issues[0].id == "workflow_changes"
    assert lifecycle.issues[0].affected_resources == ("new_demo", "changed_demo")


def test_captured_git_workflow_add_recommends_commit_snapshot():
    status = _status(
        workflow=DetailedWorkflowStatus(
            sync_status=WorkflowSyncStatus(synced=["txt2img_basic"]),
        ),
        git=GitStatus(
            has_changes=True,
            current_branch="main",
            workflow_changes={"txt2img_basic": "added"},
        ),
    )

    lifecycle = build_lifecycle_status_from_environment_status(status)

    assert lifecycle.primary_action_id == "commit_snapshot"
    assert lifecycle.issues[0].id == "new_workflow_added"
    assert lifecycle.issues[0].layer == "snapshot"
    assert lifecycle.issues[0].source == "GitStatus.workflow_changes"
    assert lifecycle.issues[0].affected_resources == ("txt2img_basic",)
    assert "captured" in lifecycle.issues[0].message
    assert "uncommitted_changes" not in [issue.id for issue in lifecycle.issues]


def test_captured_git_workflow_changes_do_not_hide_other_git_changes():
    status = _status(
        workflow=DetailedWorkflowStatus(
            sync_status=WorkflowSyncStatus(synced=["txt2img_basic"]),
        ),
        git=GitStatus(
            has_changes=True,
            current_branch="main",
            has_other_changes=True,
            workflow_changes={"txt2img_basic": "added"},
        ),
    )

    lifecycle = build_lifecycle_status_from_environment_status(status)

    assert [issue.id for issue in lifecycle.issues] == [
        "new_workflow_added",
        "uncommitted_changes",
    ]


def test_missing_model_outranks_modified_workflow_commit_prompt():
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
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(modified=["demo"]),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="modified",
                dependencies=WorkflowDependencies(workflow_name="demo"),
                resolution=ResolutionResult(workflow_name="demo"),
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status, missing_models=[missing])
    )

    assert lifecycle.primary_action_id == "resolve_missing_model"
    assert [issue.id for issue in lifecycle.issues[:2]] == [
        "missing_required_models",
        "workflow_modified",
    ]


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


def test_downloadable_required_model_outranks_generic_workflow_model_source_issue():
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
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(synced=["demo"]),
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
                            widget_value="model.safetensors",
                        )
                    ],
                ),
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status, missing_models=[missing])
    )

    assert lifecycle.primary_action_id == "download_required_models"
    assert [issue.id for issue in lifecycle.issues] == ["missing_required_models"]


def test_missing_model_without_source_recommends_model_resolution():
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

    assert lifecycle.primary_action_id == "resolve_missing_model"
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


def test_runtime_import_failures_warn_without_blocking_commit():
    status = _status(git=GitStatus(has_changes=True, current_branch="main"))

    lifecycle = build_lifecycle_status_from_environment_status(
        status,
        runtime_state=LifecycleRuntimeState(import_errors=("ComfyUI-Impact-Pack",)),
    )

    assert [issue.id for issue in lifecycle.issues] == [
        "runtime_import_failure",
        "uncommitted_changes",
    ]
    assert lifecycle.issues[0].severity == "warning"
    assert lifecycle.issues[0].blocking is False

    commit = next(action for action in lifecycle.actions if action.id == "commit_snapshot")
    assert commit.enabled is True


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


def test_stale_workflow_dependency_metadata_recommends_refresh_capture():
    workflow_status = DetailedWorkflowStatus(
        sync_status=WorkflowSyncStatus(synced=["demo"]),
        analyzed_workflows=[
            WorkflowAnalysisStatus(
                name="demo",
                sync_state="synced",
                dependencies=WorkflowDependencies(workflow_name="demo"),
                resolution=ResolutionResult(workflow_name="demo"),
                dependency_metadata_stale=True,
            )
        ],
    )

    lifecycle = build_lifecycle_status_from_environment_status(
        _status(workflow=workflow_status)
    )

    assert lifecycle.primary_action_id == "refresh_workflow_capture"
    assert lifecycle.issues[0].id == "workflow_dependency_metadata_stale"
    assert lifecycle.issues[0].layer == "manifest"
    assert lifecycle.issues[0].affected_resources == ("demo",)


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

    assert lifecycle.primary_action_id == "resolve_missing_model"
    assert lifecycle.issues[0].id == "missing_model_source"
