"""Typed lifecycle status models for environment health and next actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

LifecycleLayer = Literal[
    "manifest",
    "filesystem",
    "runtime",
    "snapshot",
    "workspace_index",
    "operation",
]

LifecycleLayerStatus = Literal["ok", "attention", "blocked", "unknown"]
LifecycleSeverity = Literal["info", "warning", "error"]

LifecycleIssueID = Literal[
    "setup_required",
    "operation_in_progress",
    "detached_head",
    "uncommitted_changes",
    "dependencies_not_synced",
    "missing_declared_nodes",
    "missing_development_nodes",
    "untracked_node_folder",
    "untracked_development_node",
    "node_version_mismatch",
    "disabled_node",
    "workflow_changes",
    "workflow_download_intents",
    "workflow_unresolved_nodes",
    "workflow_uninstalled_nodes",
    "workflow_version_gated_nodes",
    "workflow_uninstallable_nodes",
    "missing_required_models",
    "missing_model_source",
    "model_path_mismatch",
    "model_category_mismatch",
    "runtime_restart_required",
    "runtime_import_failure",
    "comfyui_unreachable",
    "node_provenance_missing",
    "model_source_missing",
    "build_readiness_blocked",
]

LifecycleActionID = Literal[
    "setup_workspace",
    "create_environment",
    "import_existing_environment",
    "sync_environment",
    "repair_environment",
    "sync_missing_nodes",
    "review_untracked_node",
    "track_dev_node",
    "remove_untracked_node",
    "restore_or_relink_dev_node",
    "review_workflow_changes",
    "resolve_workflow_nodes",
    "sync_model_paths",
    "download_required_models",
    "add_model_source",
    "add_node_source_info",
    "restart_comfyui",
    "view_runtime_import_error",
    "commit_snapshot",
    "create_branch",
    "push_snapshot",
    "export_environment",
    "deploy_environment",
    "fix_build_readiness",
    "view_operation_logs",
]

LIFECYCLE_LAYERS: tuple[LifecycleLayer, ...] = (
    "manifest",
    "filesystem",
    "runtime",
    "snapshot",
    "workspace_index",
    "operation",
)

LIFECYCLE_ACTION_IDS: tuple[str, ...] = (
    "setup_workspace",
    "create_environment",
    "import_existing_environment",
    "sync_environment",
    "repair_environment",
    "sync_missing_nodes",
    "review_untracked_node",
    "track_dev_node",
    "remove_untracked_node",
    "restore_or_relink_dev_node",
    "review_workflow_changes",
    "resolve_workflow_nodes",
    "sync_model_paths",
    "download_required_models",
    "add_model_source",
    "add_node_source_info",
    "restart_comfyui",
    "view_runtime_import_error",
    "commit_snapshot",
    "create_branch",
    "push_snapshot",
    "export_environment",
    "deploy_environment",
    "fix_build_readiness",
    "view_operation_logs",
)

LIFECYCLE_ISSUE_IDS: tuple[str, ...] = (
    "setup_required",
    "operation_in_progress",
    "detached_head",
    "uncommitted_changes",
    "dependencies_not_synced",
    "missing_declared_nodes",
    "missing_development_nodes",
    "untracked_node_folder",
    "untracked_development_node",
    "node_version_mismatch",
    "disabled_node",
    "workflow_changes",
    "workflow_download_intents",
    "workflow_unresolved_nodes",
    "workflow_uninstalled_nodes",
    "workflow_version_gated_nodes",
    "workflow_uninstallable_nodes",
    "missing_required_models",
    "missing_model_source",
    "model_path_mismatch",
    "model_category_mismatch",
    "runtime_restart_required",
    "runtime_import_failure",
    "comfyui_unreachable",
    "node_provenance_missing",
    "model_source_missing",
    "build_readiness_blocked",
)


@dataclass(frozen=True)
class LifecycleIssue:
    """One lifecycle issue produced by core or adapter-provided runtime state."""

    id: LifecycleIssueID
    layer: LifecycleLayer
    severity: LifecycleSeverity
    message: str
    blocking: bool = False
    affected_resources: tuple[str, ...] = ()
    source: str | None = None
    details: tuple[str, ...] = ()
    action_ids: tuple[LifecycleActionID, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "layer": self.layer,
            "severity": self.severity,
            "message": self.message,
            "blocking": self.blocking,
            "affected_resources": list(self.affected_resources),
            "source": self.source,
            "details": list(self.details),
            "action_ids": list(self.action_ids),
        }


@dataclass(frozen=True)
class LifecycleAction:
    """One stable action adapters can render as a command, button, or link."""

    id: LifecycleActionID
    label: str
    description: str
    target_layer: LifecycleLayer
    issue_ids: tuple[LifecycleIssueID, ...] = ()
    expected_mutation_layers: tuple[LifecycleLayer, ...] = ()
    enabled: bool = True
    disabled_reason: str | None = None
    destructive: bool = False
    restart_required: bool = False
    confirmation_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "target_layer": self.target_layer,
            "issue_ids": list(self.issue_ids),
            "expected_mutation_layers": list(self.expected_mutation_layers),
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
            "destructive": self.destructive,
            "restart_required": self.restart_required,
            "confirmation_required": self.confirmation_required,
        }


@dataclass(frozen=True)
class LifecycleLayerSummary:
    """Rollup for one lifecycle layer."""

    layer: LifecycleLayer
    status: LifecycleLayerStatus = "unknown"
    message: str | None = None
    issue_count: int = 0
    blocking_count: int = 0

    @classmethod
    def from_issues(
        cls,
        layer: LifecycleLayer,
        issues: tuple[LifecycleIssue, ...],
        *,
        message: str | None = None,
    ) -> LifecycleLayerSummary:
        matching_issues = tuple(issue for issue in issues if issue.layer == layer)
        blocking_count = sum(1 for issue in matching_issues if issue.blocking)
        if blocking_count:
            status: LifecycleLayerStatus = "blocked"
        elif matching_issues:
            status = "attention"
        else:
            status = "ok"
        return cls(
            layer=layer,
            status=status,
            message=message,
            issue_count=len(matching_issues),
            blocking_count=blocking_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "status": self.status,
            "message": self.message,
            "issue_count": self.issue_count,
            "blocking_count": self.blocking_count,
        }


@dataclass(frozen=True)
class LifecycleRuntimeState:
    """Runtime state supplied by adapters that supervise or observe ComfyUI."""

    comfyui_reachable: bool | None = None
    restart_required: bool = False
    import_errors: tuple[str, ...] = ()
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "comfyui_reachable": self.comfyui_reachable,
            "restart_required": self.restart_required,
            "import_errors": list(self.import_errors),
            "message": self.message,
        }


@dataclass(frozen=True)
class LifecycleOperationState:
    """Current or recent mutation state supplied by CLI or Manager."""

    active: bool = False
    failed: bool = False
    name: str | None = None
    message: str | None = None
    log_reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "failed": self.failed,
            "name": self.name,
            "message": self.message,
            "log_reference": self.log_reference,
        }


@dataclass(frozen=True)
class EnvironmentLifecycleStatus:
    """Composed environment health and next-action status."""

    environment_name: str | None = None
    workspace_path: str | None = None
    current_branch: str | None = None
    current_commit: str | None = None
    detached_head: bool = False
    layers: tuple[LifecycleLayerSummary, ...] = ()
    issues: tuple[LifecycleIssue, ...] = ()
    actions: tuple[LifecycleAction, ...] = ()
    primary_action_id: LifecycleActionID | None = None

    @property
    def primary_action(self) -> LifecycleAction | None:
        """Return the explicitly selected action or the first enabled action."""
        if self.primary_action_id is not None:
            for action in self.actions:
                if action.id == self.primary_action_id:
                    return action
        for action in self.actions:
            if action.enabled:
                return action
        return None

    def layer(self, layer: LifecycleLayer) -> LifecycleLayerSummary | None:
        """Return a layer summary by ID."""
        for summary in self.layers:
            if summary.layer == layer:
                return summary
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment_name": self.environment_name,
            "workspace_path": self.workspace_path,
            "current_branch": self.current_branch,
            "current_commit": self.current_commit,
            "detached_head": self.detached_head,
            "layers": [layer.to_dict() for layer in self.layers],
            "issues": [issue.to_dict() for issue in self.issues],
            "actions": [action.to_dict() for action in self.actions],
            "primary_action_id": self.primary_action.id if self.primary_action else None,
        }
