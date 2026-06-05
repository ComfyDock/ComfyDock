"""Pure lifecycle status decision policy for environment health."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from comfygit_core.models import (
    EnvironmentLifecycleStatus,
    EnvironmentReadiness,
    EnvironmentStatus,
    LifecycleAction,
    LifecycleActionID,
    LifecycleIssue,
    LifecycleIssueID,
    LifecycleLayer,
    LifecycleLayerSummary,
    LifecycleOperationState,
    LifecycleRuntimeState,
    LifecycleSeverity,
    MissingModelInfo,
)
from comfygit_core.models.workflow import WorkflowSyncStatus


def build_lifecycle_status_from_environment_status(
    status: EnvironmentStatus,
    *,
    environment_name: str | None = None,
    workspace_path: str | None = None,
    current_commit: str | None = None,
    readiness: EnvironmentReadiness | None = None,
    runtime_state: LifecycleRuntimeState | None = None,
    operation_state: LifecycleOperationState | None = None,
) -> EnvironmentLifecycleStatus:
    """Build a composed lifecycle status from existing core/adapted signals.

    This function is intentionally side-effect free. It does not scan the
    environment; callers pass already-computed core status plus any adapter-owned
    runtime/operation state they want included in the decision.
    """
    builder = _LifecycleStatusBuilder()

    _collect_operation_issues(builder, operation_state)
    _collect_snapshot_safety_issues(builder, status)
    _collect_materialization_issues(builder, status)
    _collect_missing_model_issues(builder, status)
    _collect_workflow_issues(builder, status)
    _collect_runtime_issues(builder, runtime_state)
    _collect_readiness_issues(builder, readiness)
    _collect_snapshot_action(builder, status)

    issues = tuple(builder.issues)
    layers = tuple(
        LifecycleLayerSummary.from_issues(layer, issues)
        for layer in (
            "manifest",
            "filesystem",
            "runtime",
            "snapshot",
            "workspace_index",
            "operation",
        )
    )
    actions = tuple(builder.actions)
    primary_action = next((action for action in actions if action.enabled), None)

    return EnvironmentLifecycleStatus(
        environment_name=environment_name,
        workspace_path=workspace_path,
        current_branch=status.git.current_branch,
        current_commit=current_commit,
        detached_head=status.git.current_branch is None,
        layers=layers,
        issues=issues,
        actions=actions,
        primary_action_id=primary_action.id if primary_action else None,
    )


class _LifecycleStatusBuilder:
    """Mutable assembly helper for a single lifecycle decision pass."""

    def __init__(self) -> None:
        self.issues: list[LifecycleIssue] = []
        self.actions: list[LifecycleAction] = []

    @property
    def has_blocking_issues(self) -> bool:
        return any(issue.blocking for issue in self.issues)

    def add_issue(
        self,
        *,
        id: LifecycleIssueID,
        layer: LifecycleLayer,
        severity: str,
        message: str,
        blocking: bool = False,
        affected_resources: Iterable[str] = (),
        source: str | None = None,
        details: Iterable[str] = (),
        action_ids: Iterable[LifecycleActionID] = (),
    ) -> None:
        self.issues.append(
            LifecycleIssue(
                id=id,
                layer=layer,
                severity=cast(LifecycleSeverity, severity),
                message=message,
                blocking=blocking,
                affected_resources=tuple(affected_resources),
                source=source,
                details=tuple(details),
                action_ids=tuple(action_ids),
            )
        )

    def add_action(
        self,
        id: LifecycleActionID,
        *,
        issue_ids: Iterable[LifecycleIssueID] = (),
        enabled: bool = True,
        disabled_reason: str | None = None,
    ) -> None:
        action = _make_action(
            id,
            issue_ids=tuple(issue_ids),
            enabled=enabled,
            disabled_reason=disabled_reason,
        )
        self._append_or_merge_action(action)

    def _append_or_merge_action(self, action: LifecycleAction) -> None:
        for index, existing in enumerate(self.actions):
            if existing.id != action.id:
                continue
            issue_ids = tuple(dict.fromkeys(existing.issue_ids + action.issue_ids))
            expected_layers = tuple(
                dict.fromkeys(
                    existing.expected_mutation_layers + action.expected_mutation_layers
                )
            )
            self.actions[index] = LifecycleAction(
                id=existing.id,
                label=existing.label,
                description=existing.description,
                target_layer=existing.target_layer,
                issue_ids=issue_ids,
                expected_mutation_layers=expected_layers,
                enabled=existing.enabled and action.enabled,
                disabled_reason=existing.disabled_reason or action.disabled_reason,
                destructive=existing.destructive or action.destructive,
                restart_required=existing.restart_required or action.restart_required,
                confirmation_required=(
                    existing.confirmation_required or action.confirmation_required
                ),
            )
            return
        self.actions.append(action)


def _collect_operation_issues(
    builder: _LifecycleStatusBuilder,
    operation_state: LifecycleOperationState | None,
) -> None:
    if operation_state is None or not operation_state.active:
        return
    name = operation_state.name or "operation"
    message = operation_state.message or f"{name} is in progress."
    builder.add_issue(
        id="operation_in_progress",
        layer="operation",
        severity="info",
        message=message,
        blocking=True,
        source="LifecycleOperationState.active",
        action_ids=("view_operation_logs",),
    )
    builder.add_action("view_operation_logs", issue_ids=("operation_in_progress",))


def _collect_snapshot_safety_issues(
    builder: _LifecycleStatusBuilder,
    status: EnvironmentStatus,
) -> None:
    if status.git.current_branch is not None:
        return
    builder.add_issue(
        id="detached_head",
        layer="snapshot",
        severity="error",
        message="Environment is on a detached HEAD.",
        blocking=True,
        source="GitStatus.current_branch",
        action_ids=("create_branch",),
    )
    builder.add_action("create_branch", issue_ids=("detached_head",))


def _collect_materialization_issues(
    builder: _LifecycleStatusBuilder,
    status: EnvironmentStatus,
) -> None:
    comparison = status.comparison

    if not comparison.packages_in_sync:
        builder.add_issue(
            id="dependencies_not_synced",
            layer="filesystem",
            severity="error",
            message=comparison.package_sync_message or "Python dependencies are not synced.",
            blocking=True,
            source="EnvironmentComparison.packages_in_sync",
            action_ids=("sync_environment",),
        )
        builder.add_action("sync_environment", issue_ids=("dependencies_not_synced",))

    if comparison.missing_nodes:
        builder.add_issue(
            id="missing_declared_nodes",
            layer="filesystem",
            severity="error",
            message="Manifest declares custom nodes that are missing on disk.",
            blocking=True,
            affected_resources=comparison.missing_nodes,
            source="EnvironmentComparison.missing_nodes",
            action_ids=("sync_missing_nodes",),
        )
        builder.add_action("sync_missing_nodes", issue_ids=("missing_declared_nodes",))

    if comparison.dev_nodes_missing:
        builder.add_issue(
            id="missing_development_nodes",
            layer="filesystem",
            severity="warning",
            message="Development nodes declared by the manifest are missing locally.",
            affected_resources=comparison.dev_nodes_missing,
            source="EnvironmentComparison.dev_nodes_missing",
            action_ids=("restore_or_relink_dev_node",),
        )
        builder.add_action("restore_or_relink_dev_node", issue_ids=("missing_development_nodes",))

    if comparison.version_mismatches:
        resources = [
            str(item.get("name", "unknown"))
            for item in comparison.version_mismatches
            if isinstance(item, dict)
        ]
        builder.add_issue(
            id="node_version_mismatch",
            layer="filesystem",
            severity="warning",
            message="Installed custom node versions differ from the manifest.",
            affected_resources=resources,
            source="EnvironmentComparison.version_mismatches",
            details=[str(item) for item in comparison.version_mismatches],
            action_ids=("repair_environment",),
        )
        builder.add_action("repair_environment", issue_ids=("node_version_mismatch",))

    if comparison.extra_nodes:
        builder.add_issue(
            id="untracked_node_folder",
            layer="filesystem",
            severity="warning",
            message="Custom node folders exist on disk but are not tracked.",
            affected_resources=comparison.extra_nodes,
            source="EnvironmentComparison.extra_nodes",
            action_ids=("review_untracked_node", "remove_untracked_node"),
        )
        builder.add_action("review_untracked_node", issue_ids=("untracked_node_folder",))
        builder.add_action("remove_untracked_node", issue_ids=("untracked_node_folder"))

    if comparison.dev_nodes_untracked:
        builder.add_issue(
            id="untracked_development_node",
            layer="filesystem",
            severity="warning",
            message="Development node checkouts exist on disk but are not tracked.",
            affected_resources=comparison.dev_nodes_untracked,
            source="EnvironmentComparison.dev_nodes_untracked",
            action_ids=("track_dev_node",),
        )
        builder.add_action("track_dev_node", issue_ids=("untracked_development_node",))

    if comparison.disabled_nodes:
        builder.add_issue(
            id="disabled_node",
            layer="filesystem",
            severity="warning",
            message="Declared custom nodes are disabled on disk.",
            affected_resources=comparison.disabled_nodes,
            source="EnvironmentComparison.disabled_nodes",
            action_ids=("repair_environment",),
        )
        builder.add_action("repair_environment", issue_ids=("disabled_node",))


def _collect_workflow_issues(
    builder: _LifecycleStatusBuilder,
    status: EnvironmentStatus,
) -> None:
    workflow_status = status.workflow
    sync_status = workflow_status.sync_status
    required_missing_by_workflow = _required_missing_models_by_workflow(status)

    unresolved_node_workflows: list[str] = []
    uninstalled_node_workflows: list[str] = []
    version_gated_workflows: list[str] = []
    uninstallable_workflows: list[str] = []
    unresolved_model_workflows: list[str] = []
    path_sync_workflows: list[str] = []
    category_mismatch_workflows: list[str] = []
    download_intent_workflows: list[str] = []

    for workflow in workflow_status.analyzed_workflows:
        resolution = workflow.resolution
        if (
            resolution.nodes_unresolved
            or resolution.nodes_ambiguous
        ):
            unresolved_node_workflows.append(workflow.name)
        if workflow.uninstalled_nodes:
            uninstalled_node_workflows.append(workflow.name)
        if resolution.nodes_version_gated:
            version_gated_workflows.append(workflow.name)
        if resolution.nodes_uninstallable:
            uninstallable_workflows.append(workflow.name)
        if resolution.models_unresolved or resolution.models_ambiguous:
            required_missing = required_missing_by_workflow.get(workflow.name, ())
            if not required_missing or not all(model.can_download for model in required_missing):
                unresolved_model_workflows.append(workflow.name)
        if workflow.has_path_sync_issues:
            path_sync_workflows.append(workflow.name)
        if workflow.has_category_mismatch_issues:
            category_mismatch_workflows.append(workflow.name)
        if resolution.has_download_intents:
            download_intent_workflows.append(workflow.name)

    if unresolved_node_workflows:
        builder.add_issue(
            id="workflow_unresolved_nodes",
            layer="manifest",
            severity="error",
            message="Workflows contain custom nodes that are not resolved.",
            blocking=True,
            affected_resources=unresolved_node_workflows,
            source="WorkflowAnalysisStatus.resolution.nodes_unresolved",
            action_ids=("resolve_workflow_nodes",),
        )
        builder.add_action("resolve_workflow_nodes", issue_ids=("workflow_unresolved_nodes",))

    if uninstalled_node_workflows:
        builder.add_issue(
            id="workflow_uninstalled_nodes",
            layer="filesystem",
            severity="error",
            message="Tracked workflow packages are not installed locally.",
            blocking=True,
            affected_resources=uninstalled_node_workflows,
            source="WorkflowAnalysisStatus.uninstalled_nodes",
            action_ids=("sync_missing_nodes",),
        )
        builder.add_action("sync_missing_nodes", issue_ids=("workflow_uninstalled_nodes",))

    if version_gated_workflows:
        builder.add_issue(
            id="workflow_version_gated_nodes",
            layer="manifest",
            severity="error",
            message="Workflows contain built-in nodes that need a newer ComfyUI version.",
            blocking=True,
            affected_resources=version_gated_workflows,
            source="ResolutionResult.nodes_version_gated",
            action_ids=("resolve_workflow_nodes",),
        )
        builder.add_action("resolve_workflow_nodes", issue_ids=("workflow_version_gated_nodes",))

    if uninstallable_workflows:
        builder.add_issue(
            id="workflow_uninstallable_nodes",
            layer="manifest",
            severity="error",
            message="Workflows map to node packages without an installable source.",
            blocking=True,
            affected_resources=uninstallable_workflows,
            source="ResolutionResult.nodes_uninstallable",
            action_ids=("resolve_workflow_nodes",),
        )
        builder.add_action("resolve_workflow_nodes", issue_ids=("workflow_uninstallable_nodes",))

    if unresolved_model_workflows:
        builder.add_issue(
            id="missing_model_source",
            layer="workspace_index",
            severity="error",
            message="Workflows reference models that are not available or sourced.",
            blocking=True,
            affected_resources=unresolved_model_workflows,
            source="ResolutionResult.models_unresolved",
            action_ids=("resolve_missing_model",),
        )
        builder.add_action("resolve_missing_model", issue_ids=("missing_model_source",))

    if category_mismatch_workflows:
        builder.add_issue(
            id="model_category_mismatch",
            layer="filesystem",
            severity="error",
            message="Resolved models are in folders incompatible with their loaders.",
            blocking=True,
            affected_resources=category_mismatch_workflows,
            source="WorkflowAnalysisStatus.has_category_mismatch_issues",
            action_ids=("download_required_models",),
        )
        builder.add_action("download_required_models", issue_ids=("model_category_mismatch",))

    if path_sync_workflows:
        builder.add_issue(
            id="model_path_mismatch",
            layer="manifest",
            severity="warning",
            message="Workflow model paths differ from indexed local model paths.",
            affected_resources=path_sync_workflows,
            source="WorkflowAnalysisStatus.has_path_sync_issues",
            action_ids=("sync_model_paths",),
        )
        builder.add_action("sync_model_paths", issue_ids=("model_path_mismatch",))

    if download_intent_workflows:
        builder.add_issue(
            id="workflow_download_intents",
            layer="workspace_index",
            severity="warning",
            message="Workflows have model downloads queued or pending.",
            affected_resources=download_intent_workflows,
            source="ResolutionResult.has_download_intents",
            action_ids=("download_required_models",),
        )
        builder.add_action("download_required_models", issue_ids=("workflow_download_intents",))

    if sync_status.has_changes:
        _collect_workflow_file_snapshot_issue(builder, sync_status)


def _collect_workflow_file_snapshot_issue(
    builder: _LifecycleStatusBuilder,
    sync_status: WorkflowSyncStatus,
) -> None:
    changed_groups = sum(
        1
        for resources in (sync_status.new, sync_status.modified, sync_status.deleted)
        if resources
    )
    affected = tuple(sync_status.new + sync_status.modified + sync_status.deleted)

    issue_id: LifecycleIssueID
    source: str
    if changed_groups == 1 and sync_status.new:
        issue_id = "new_workflow_added"
        message = (
            "New workflow saved in ComfyUI and not yet captured in the "
            "environment snapshot."
            if len(sync_status.new) == 1
            else "New workflows saved in ComfyUI and not yet captured in the "
            "environment snapshot."
        )
        source = "WorkflowSyncStatus.new"
    elif changed_groups == 1 and sync_status.modified:
        issue_id = "workflow_modified"
        message = (
            "Workflow modified in ComfyUI and not yet captured in the "
            "environment snapshot."
            if len(sync_status.modified) == 1
            else "Workflows modified in ComfyUI and not yet captured in the "
            "environment snapshot."
        )
        source = "WorkflowSyncStatus.modified"
    elif changed_groups == 1 and sync_status.deleted:
        issue_id = "workflow_deleted"
        message = (
            "Workflow removed from ComfyUI and not yet captured in the "
            "environment snapshot."
            if len(sync_status.deleted) == 1
            else "Workflows removed from ComfyUI and not yet captured in the "
            "environment snapshot."
        )
        source = "WorkflowSyncStatus.deleted"
    else:
        issue_id = "workflow_changes"
        message = (
            "Workflow file changes in ComfyUI are not yet captured in the "
            "environment snapshot."
        )
        source = "WorkflowSyncStatus.has_changes"

    enabled = not builder.has_blocking_issues
    disabled_reason = (
        None if enabled else "Resolve blocking lifecycle issues before committing."
    )
    builder.add_issue(
        id=issue_id,
        layer="snapshot",
        severity="warning",
        message=message,
        affected_resources=affected,
        source=source,
        action_ids=("commit_snapshot", "review_workflow_changes"),
    )
    builder.add_action(
        "commit_snapshot",
        issue_ids=(issue_id,),
        enabled=enabled,
        disabled_reason=disabled_reason,
    )
    builder.add_action("review_workflow_changes", issue_ids=(issue_id,))


def _required_missing_models_by_workflow(
    status: EnvironmentStatus,
) -> dict[str, tuple[MissingModelInfo, ...]]:
    by_workflow: dict[str, list[MissingModelInfo]] = {}
    for model in status.missing_models:
        if not model.is_required:
            continue
        for workflow_name in model.workflow_names:
            by_workflow.setdefault(workflow_name, []).append(model)
    return {
        workflow_name: tuple(models)
        for workflow_name, models in by_workflow.items()
    }


def _collect_missing_model_issues(
    builder: _LifecycleStatusBuilder,
    status: EnvironmentStatus,
) -> None:
    if not status.missing_models:
        return

    required_missing = [model for model in status.missing_models if model.is_required]
    if not required_missing:
        return

    affected = [model.model.filename for model in required_missing]
    can_download_all = all(model.can_download for model in required_missing)
    action_id: LifecycleActionID = (
        "download_required_models" if can_download_all else "resolve_missing_model"
    )
    builder.add_issue(
        id="missing_required_models",
        layer="filesystem",
        severity="error",
        message="Required manifest models are missing locally.",
        blocking=True,
        affected_resources=affected,
        source="EnvironmentStatus.missing_models",
        action_ids=(action_id,),
    )
    builder.add_action(action_id, issue_ids=("missing_required_models",))


def _collect_runtime_issues(
    builder: _LifecycleStatusBuilder,
    runtime_state: LifecycleRuntimeState | None,
) -> None:
    if runtime_state is None:
        return
    if runtime_state.import_errors:
        builder.add_issue(
            id="runtime_import_failure",
            layer="runtime",
            severity="warning",
            message="ComfyUI reported custom-node import failures.",
            affected_resources=runtime_state.import_errors,
            source="LifecycleRuntimeState.import_errors",
            action_ids=("view_runtime_import_error",),
        )
        builder.add_action(
            "view_runtime_import_error",
            issue_ids=("runtime_import_failure",),
        )
    if runtime_state.comfyui_reachable is False:
        builder.add_issue(
            id="comfyui_unreachable",
            layer="runtime",
            severity="warning",
            message=runtime_state.message or "ComfyUI is not reachable.",
            source="LifecycleRuntimeState.comfyui_reachable",
            action_ids=("restart_comfyui",),
        )
        builder.add_action("restart_comfyui", issue_ids=("comfyui_unreachable",))
    if runtime_state.restart_required:
        builder.add_issue(
            id="runtime_restart_required",
            layer="runtime",
            severity="warning",
            message="Restart ComfyUI to load materialized environment changes.",
            source="LifecycleRuntimeState.restart_required",
            action_ids=("restart_comfyui",),
        )
        builder.add_action("restart_comfyui", issue_ids=("runtime_restart_required",))


def _collect_readiness_issues(
    builder: _LifecycleStatusBuilder,
    readiness: EnvironmentReadiness | None,
) -> None:
    if readiness is None:
        return

    if readiness.blocking_issues:
        builder.add_issue(
            id="build_readiness_blocked",
            layer="snapshot",
            severity="error",
            message="Environment handoff readiness has blocking issues.",
            blocking=True,
            affected_resources=[issue.type for issue in readiness.blocking_issues],
            source="EnvironmentReadiness.blocking_issues",
            action_ids=("fix_build_readiness",),
        )
        builder.add_action("fix_build_readiness", issue_ids=("build_readiness_blocked",))

    if readiness.warnings.nodes_without_provenance:
        builder.add_issue(
            id="node_provenance_missing",
            layer="snapshot",
            severity="warning",
            message="Some custom nodes are missing portable source metadata.",
            affected_resources=[
                warning.name for warning in readiness.warnings.nodes_without_provenance
            ],
            source="ReadinessWarnings.nodes_without_provenance",
            action_ids=("add_node_source_info",),
        )
        builder.add_action("add_node_source_info", issue_ids=("node_provenance_missing",))

    if readiness.warnings.models_without_sources:
        builder.add_issue(
            id="model_source_missing",
            layer="snapshot",
            severity="warning",
            message="Some manifest models are missing portable source metadata.",
            affected_resources=[
                warning.filename for warning in readiness.warnings.models_without_sources
            ],
            source="ReadinessWarnings.models_without_sources",
            action_ids=("add_model_source",),
        )
        builder.add_action("add_model_source", issue_ids=("model_source_missing",))


def _collect_snapshot_action(
    builder: _LifecycleStatusBuilder,
    status: EnvironmentStatus,
) -> None:
    if not status.git.has_changes:
        return
    enabled = not builder.has_blocking_issues
    builder.add_issue(
        id="uncommitted_changes",
        layer="snapshot",
        severity="warning",
        message="Environment repository has uncommitted changes.",
        source="GitStatus.has_changes",
        action_ids=("commit_snapshot",),
    )
    builder.add_action(
        "commit_snapshot",
        issue_ids=("uncommitted_changes",),
        enabled=enabled,
        disabled_reason=(
            None if enabled else "Resolve blocking lifecycle issues before committing."
        ),
    )


def _make_action(
    id: LifecycleActionID,
    *,
    issue_ids: tuple[LifecycleIssueID, ...] = (),
    enabled: bool = True,
    disabled_reason: str | None = None,
) -> LifecycleAction:
    label, description, layer, mutation_layers, flags = _ACTION_DEFINITIONS[id]
    return LifecycleAction(
        id=id,
        label=label,
        description=description,
        target_layer=layer,
        issue_ids=issue_ids,
        expected_mutation_layers=mutation_layers,
        enabled=enabled,
        disabled_reason=disabled_reason,
        destructive=flags.get("destructive", False),
        restart_required=flags.get("restart_required", False),
        confirmation_required=flags.get("confirmation_required", False),
    )


_ACTION_DEFINITIONS: dict[
    LifecycleActionID,
    tuple[str, str, LifecycleLayer, tuple[LifecycleLayer, ...], dict[str, bool]],
] = {
    "setup_workspace": (
        "Set up workspace",
        "Create or open a ComfyGit workspace.",
        "manifest",
        ("manifest",),
        {},
    ),
    "create_environment": (
        "Create environment",
        "Create a managed ComfyGit environment.",
        "manifest",
        ("manifest", "filesystem"),
        {},
    ),
    "import_existing_environment": (
        "Import existing environment",
        "Capture an unmanaged ComfyUI environment into ComfyGit.",
        "manifest",
        ("manifest", "filesystem", "workspace_index"),
        {},
    ),
    "sync_environment": (
        "Sync environment",
        "Reconcile manifest-declared state into the local filesystem.",
        "filesystem",
        ("filesystem", "operation"),
        {"restart_required": True},
    ),
    "repair_environment": (
        "Repair environment",
        "Repair detected environment drift.",
        "filesystem",
        ("filesystem", "operation"),
        {"confirmation_required": True, "restart_required": True},
    ),
    "sync_missing_nodes": (
        "Sync missing nodes",
        "Install node folders declared by the manifest.",
        "filesystem",
        ("filesystem", "operation"),
        {"restart_required": True},
    ),
    "review_untracked_node": (
        "Review untracked node",
        "Decide whether to track, remove, or ignore the node folder.",
        "filesystem",
        ("manifest", "filesystem"),
        {"confirmation_required": True},
    ),
    "track_dev_node": (
        "Track development node",
        "Capture the development node checkout in the manifest.",
        "manifest",
        ("manifest",),
        {"confirmation_required": True},
    ),
    "remove_untracked_node": (
        "Remove untracked node",
        "Remove the untracked node folder from disk.",
        "filesystem",
        ("filesystem",),
        {"confirmation_required": True, "destructive": True, "restart_required": True},
    ),
    "restore_or_relink_dev_node": (
        "Restore development node",
        "Restore or untrack a missing local development node checkout.",
        "filesystem",
        ("filesystem", "manifest"),
        {"confirmation_required": True, "restart_required": True},
    ),
    "review_workflow_changes": (
        "Review workflow changes",
        "Review ComfyUI workflow file changes before snapshotting them.",
        "manifest",
        ("manifest", "snapshot"),
        {},
    ),
    "resolve_workflow_nodes": (
        "Resolve workflow nodes",
        "Choose packages for unresolved workflow custom nodes.",
        "manifest",
        ("manifest", "workspace_index"),
        {},
    ),
    "sync_model_paths": (
        "Sync model paths",
        "Update workflow model paths to match indexed local model locations.",
        "manifest",
        ("manifest",),
        {},
    ),
    "download_required_models": (
        "Download required models",
        "Download required model files from known sources.",
        "filesystem",
        ("filesystem", "workspace_index"),
        {},
    ),
    "resolve_missing_model": (
        "Resolve models",
        "Choose how missing workflow model references should be resolved.",
        "workspace_index",
        ("manifest", "filesystem", "workspace_index"),
        {},
    ),
    "add_model_source": (
        "Add model source",
        "Add source/provenance metadata for models that already exist locally.",
        "workspace_index",
        ("manifest", "workspace_index"),
        {"confirmation_required": True},
    ),
    "add_node_source_info": (
        "Add node source info",
        "Add portable source metadata for custom nodes.",
        "snapshot",
        ("manifest",),
        {"confirmation_required": True},
    ),
    "restart_comfyui": (
        "Restart ComfyUI",
        "Restart ComfyUI to load the current environment state.",
        "runtime",
        ("runtime", "operation"),
        {},
    ),
    "view_runtime_import_error": (
        "View import error",
        "Open runtime import error details.",
        "runtime",
        ("runtime",),
        {},
    ),
    "commit_snapshot": (
        "Commit snapshot",
        "Commit the current desired environment state.",
        "snapshot",
        ("manifest", "snapshot"),
        {},
    ),
    "create_branch": (
        "Create branch",
        "Create or checkout a branch before committing changes.",
        "snapshot",
        ("snapshot",),
        {},
    ),
    "push_snapshot": (
        "Push snapshot",
        "Push committed environment snapshots to the remote repository.",
        "snapshot",
        ("snapshot",),
        {},
    ),
    "export_environment": (
        "Export environment",
        "Export a reproducible environment snapshot.",
        "snapshot",
        ("snapshot",),
        {},
    ),
    "deploy_environment": (
        "Deploy environment",
        "Deploy a committed environment snapshot.",
        "snapshot",
        ("snapshot",),
        {"confirmation_required": True},
    ),
    "fix_build_readiness": (
        "Fix build blockers",
        "Review and fix build readiness blockers before handoff.",
        "snapshot",
        ("manifest", "snapshot", "workspace_index"),
        {"confirmation_required": True},
    ),
    "view_operation_logs": (
        "View progress",
        "View logs for the active operation.",
        "operation",
        ("operation",),
        {},
    ),
}
