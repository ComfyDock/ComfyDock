"""Typed readiness result models for portable environment handoff."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from .manifest import EnvironmentManifestSnapshot

ReadinessBlockingIssueType = Literal[
    "uncommitted_workflows",
    "uncommitted_git_changes",
    "unresolved_issues",
    "missing_contract_api_prompts",
    "invalid_contract_api_prompt_paths",
]

DependencyCriticality = Literal["required", "optional"]


class ReadinessWorkflowStatusReader(Protocol):
    """Minimal workflow status reader needed by readiness checks."""

    def get_workflow_status(self) -> ReadinessWorkflowStatus: ...


class ReadinessGitStatusReader(Protocol):
    """Minimal git status reader needed by readiness checks."""

    def has_uncommitted_changes(self) -> bool: ...


class ReadinessWorkflowSyncStatus(Protocol):
    """Minimal workflow sync-state shape needed by readiness blockers."""

    @property
    def has_changes(self) -> bool: ...

    @property
    def new(self) -> Iterable[str]: ...

    @property
    def modified(self) -> Iterable[str]: ...

    @property
    def deleted(self) -> Iterable[str]: ...


class ReadinessWorkflowStatus(Protocol):
    """Minimal workflow status shape needed by readiness blockers."""

    @property
    def sync_status(self) -> ReadinessWorkflowSyncStatus: ...

    @property
    def is_commit_safe(self) -> bool: ...


class ReadinessEnvironment(Protocol):
    """Environment-shaped object accepted by readiness context adapters."""

    @property
    def cec_path(self) -> Path: ...

    @property
    def workspace(self) -> Any: ...

    @property
    def workflow_manager(self) -> ReadinessWorkflowStatusReader: ...

    @property
    def git_manager(self) -> ReadinessGitStatusReader: ...

    def get_manifest_snapshot(self) -> EnvironmentManifestSnapshot: ...


@dataclass
class ReadinessBlockingIssue:
    """A source-state issue that blocks an immediate handoff action."""

    type: ReadinessBlockingIssueType
    message: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelSourceCandidate:
    """A known source hint for a model missing manifest source metadata."""

    type: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReadinessModelSourceReader(Protocol):
    """Reader for workspace-index model source hints."""

    def get_model_source_candidates(
        self,
        model_hash: str,
    ) -> Iterable[ModelSourceCandidate]: ...


@dataclass(frozen=True)
class ReadinessContext:
    """Typed input context for environment readiness checks.

    The context separates reusable readiness policy from concrete Environment,
    Workspace, PyprojectManager, and repository implementations.
    """

    manifest: EnvironmentManifestSnapshot
    manifest_dir: Path
    workflow_status: ReadinessWorkflowStatus | None = None
    has_uncommitted_git_changes: bool = False
    model_source_reader: ReadinessModelSourceReader | None = None


@dataclass
class ModelSourceWarning:
    """A model entry that lacks a known download source."""

    filename: str
    hash: str | None = None
    criticality: DependencyCriticality = "required"
    workflows: list[str] = field(default_factory=list)
    source_candidates: list[ModelSourceCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NodeProvenanceWarning:
    """A required custom node that lacks portable acquisition metadata."""

    name: str
    source: str
    criticality: str
    reason: str
    registry_id: str | None = None
    repository: str | None = None
    version: str | None = None
    pinned_commit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReadinessWarnings:
    """Grouped reproducibility warnings for portable handoff."""

    models_without_sources: list[ModelSourceWarning] = field(default_factory=list)
    nodes_without_provenance: list[NodeProvenanceWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "models_without_sources": [
                warning.to_dict() for warning in self.models_without_sources
            ],
            "nodes_without_provenance": [
                warning.to_dict() for warning in self.nodes_without_provenance
            ],
        }


@dataclass
class EnvironmentReadiness:
    """Structured readiness result for export, push, and future build gates."""

    blocking_issues: list[ReadinessBlockingIssue] = field(default_factory=list)
    warnings: ReadinessWarnings = field(default_factory=ReadinessWarnings)

    @property
    def can_export(self) -> bool:
        """Whether the current source state is eligible for export-style handoff."""
        return len(self.blocking_issues) == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize using the current Manager API JSON field names."""
        return {
            "can_export": self.can_export,
            "blocking_issues": [
                issue.to_dict() for issue in self.blocking_issues
            ],
            "warnings": self.warnings.to_dict(),
        }
