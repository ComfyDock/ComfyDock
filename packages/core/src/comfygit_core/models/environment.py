"""models/environment.py - Environment models for ComfyGit."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from .workflow import DetailedWorkflowStatus

if TYPE_CHECKING:
    from .manifest import ManifestModel


@dataclass
class PackageSyncStatus:
    """Status of package synchronization."""

    in_sync: bool
    message: str
    details: str | None = None


@dataclass
class GitStatus:
    """Encapsulated git status information."""

    has_changes: bool
    current_branch: str | None = None  # None = detached HEAD
    has_other_changes: bool = False  # Changes beyond workflows/pyproject
    # diff: str
    workflow_changes: dict[str, str] = field(default_factory=dict)

    # Git change details (populated by parser if needed)
    nodes_added: list[dict] = field(default_factory=list)  # {"name": str, "is_development": bool}
    nodes_removed: list[dict] = field(default_factory=list)  # {"name": str, "is_development": bool}
    dependencies_added: list[dict] = field(default_factory=list)
    dependencies_removed: list[dict] = field(default_factory=list)
    dependencies_updated: list[dict] = field(default_factory=list)
    constraints_added: list[str] = field(default_factory=list)
    constraints_removed: list[str] = field(default_factory=list)

@dataclass
class GitInfo:
    commit: str | None = None
    branch: str | None = None
    tag: str | None = None
    is_dirty: bool = False
    remote_url: str | None = None
    github_owner: str | None = None
    github_repo: str | None = None

@dataclass
class EnvironmentComparison:
    """Comparison between current and expected environment states."""

    missing_nodes: list[str] = field(default_factory=list)
    extra_nodes: list[str] = field(default_factory=list)
    disabled_nodes: list[str] = field(default_factory=list)
    version_mismatches: list[dict] = field(
        default_factory=list
    )  # {name, expected, actual}
    packages_in_sync: bool = True
    package_sync_message: str = ""
    potential_dev_rename: bool = False

    # Dev node status (informational only, not errors)
    dev_nodes_untracked: list[str] = field(default_factory=list)  # Git repos in custom_nodes but not tracked
    dev_nodes_missing: list[str] = field(default_factory=list)    # Tracked dev nodes not on filesystem

    @property
    def is_synced(self) -> bool:
        """Check if environment is fully synced.

        Note: Dev node discrepancies are informational only and don't affect sync status.
        """
        return (
            not self.missing_nodes
            and not self.extra_nodes
            and not self.version_mismatches
            and self.packages_in_sync
        )

@dataclass
class NodeState:
    """State of an installed custom node."""

    name: str
    path: Path
    disabled: bool = False
    git_commit: str | None = None
    git_branch: str | None = None
    version: str | None = None  # From git tag or pyproject
    is_dirty: bool = False
    source: str | None = None  # 'registry', 'git', 'development', etc.


@dataclass
class EnvironmentState:
    """Current state of an environment."""

    custom_nodes: dict[str, NodeState]  # name -> state
    packages: dict[str, str] | None  # name -> version
    python_version: str | None


@dataclass
class MissingModelInfo:
    """Information about a model that's in pyproject but not in local index."""
    model: "ManifestModel"  # From global models table
    workflow_names: list[str]  # Which workflows need it
    criticality: str  # "required", "flexible", "optional" (worst case across workflows)
    can_download: bool  # Has sources available

    @property
    def is_required(self) -> bool:
        return self.criticality == "required"


# === Semantic Value Objects ===


class UserAction(Enum):
    """Recommended user actions."""

    SYNC_REQUIRED = "sync"
    COMMIT_REQUIRED = "commit"
    NO_ACTION_NEEDED = "none"


@dataclass
class ChangesSummary:
    """Summary of changes with semantic meaning."""

    primary_changes: list[str] = field(default_factory=list)
    secondary_changes: list[str] = field(default_factory=list)
    has_breaking_changes: bool = False

    def get_headline(self) -> str:
        """Get a headline summary of changes."""
        if not self.primary_changes and not self.secondary_changes:
            return "No changes"

        if self.has_breaking_changes:
            return "Breaking changes detected"

        if len(self.primary_changes) == 1 and not self.secondary_changes:
            return self.primary_changes[0]

        total = len(self.primary_changes) + len(self.secondary_changes)
        return f"{total} changes"

    def get_commit_message(self) -> str:
        """Generate a commit message from changes."""
        parts = self.primary_changes + self.secondary_changes
        if not parts:
            return "Update environment configuration"
        return "; ".join(parts)




@dataclass
class EnvironmentStatus:
    """Complete environment status including comparison and git/workflow state."""

    comparison: EnvironmentComparison
    git: GitStatus
    workflow: DetailedWorkflowStatus
    missing_models: list[MissingModelInfo] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        comparison: EnvironmentComparison,
        git_status: GitStatus,
        workflow_status: DetailedWorkflowStatus,
        missing_models: list[MissingModelInfo] | None = None,
    ) -> "EnvironmentStatus":
        """Factory method to create EnvironmentStatus from components."""
        return cls(
            comparison=comparison,
            git=git_status,
            workflow=workflow_status,
            missing_models=missing_models or []
        )

    @property
    def is_synced(self) -> bool:
        """Check if environment is fully synced (nodes, packages, workflows, and models)."""
        return (
            self.comparison.is_synced and
            self.workflow.sync_status.is_synced and
            not self.missing_models
        )

    # === Semantic Methods ===

    def get_changes_summary(self) -> ChangesSummary:
        """Analyze and categorize all changes."""
        primary_changes = []
        secondary_changes = []

        # Node changes (most specific)
        if self.git.nodes_added and self.git.nodes_removed:
            primary_changes.append(
                f"Update nodes: +{len(self.git.nodes_added)}, -{len(self.git.nodes_removed)}"
            )
        elif self.git.nodes_added:
            if len(self.git.nodes_added) == 1:
                primary_changes.append(f"Add {self.git.nodes_added[0]['name']}")
            else:
                primary_changes.append(f"Add {len(self.git.nodes_added)} nodes")
        elif self.git.nodes_removed:
            if len(self.git.nodes_removed) == 1:
                primary_changes.append(f"Remove {self.git.nodes_removed[0]['name']}")
            else:
                primary_changes.append(f"Remove {len(self.git.nodes_removed)} nodes")

        # Dependency changes
        if (
            self.git.dependencies_added
            or self.git.dependencies_removed
            or self.git.dependencies_updated
        ):
            dep_count = (
                len(self.git.dependencies_added)
                + len(self.git.dependencies_removed)
                + len(self.git.dependencies_updated)
            )
            secondary_changes.append(f"Update {dep_count} dependencies")

        # Constraint changes
        if self.git.constraints_added or self.git.constraints_removed:
            secondary_changes.append("Update constraints")

        # No more workflow tracking changes - all workflows are automatically managed

        # Workflow file changes
        if self.git.workflow_changes:
            workflow_count = len(self.git.workflow_changes)
            if workflow_count == 1:
                workflow_name, workflow_status = list(
                    self.git.workflow_changes.items()
                )[0]
                if workflow_status == "modified":
                    primary_changes.append(f"Update {workflow_name}")
                elif workflow_status == "added":
                    primary_changes.append(f"Add {workflow_name}")
                elif workflow_status == "deleted":
                    primary_changes.append(f"Remove {workflow_name}")
            else:
                primary_changes.append(f"Update {workflow_count} workflows")

        # Detect breaking changes
        has_breaking = bool(
            self.git.nodes_removed
            or self.git.dependencies_removed
            or self.git.constraints_removed
        )

        return ChangesSummary(
            primary_changes=primary_changes,
            secondary_changes=secondary_changes,
            has_breaking_changes=has_breaking,
        )

    def get_recommended_action(self) -> UserAction:
        """Determine what the user should do next."""
        if not self.is_synced:
            return UserAction.SYNC_REQUIRED
        elif self.git.has_changes:
            return UserAction.COMMIT_REQUIRED
        else:
            return UserAction.NO_ACTION_NEEDED

    def generate_commit_message(self) -> str:
        """Generate a semantic commit message."""
        summary = self.get_changes_summary()
        return summary.get_commit_message()

    def get_sync_preview(self) -> dict:
        """Get preview of what sync operation will do.

        Note: WorkflowSyncStatus is from ComfyUI's perspective:
        - new: in ComfyUI but not .cec → will be REMOVED
        - deleted: in .cec but not ComfyUI → will be ADDED
        - modified: differs between ComfyUI and .cec → will be UPDATED
        """
        return {
            'nodes_to_install': self.comparison.missing_nodes,
            'nodes_to_remove': self.comparison.extra_nodes,
            'nodes_to_update': self.comparison.version_mismatches,
            'packages_to_sync': not self.comparison.packages_in_sync,
            'workflows_to_add': self.workflow.sync_status.deleted,  # Deleted from ComfyUI, will restore
            'workflows_to_update': self.workflow.sync_status.modified,  # Modified, will sync
            'workflows_to_remove': self.workflow.sync_status.new,  # New in ComfyUI, will remove
            'models_missing': self.missing_models,
            'models_downloadable': [m for m in self.missing_models if m.can_download],
            'models_unavailable': [m for m in self.missing_models if not m.can_download],
            'models_required': [m for m in self.missing_models if m.is_required],
        }
