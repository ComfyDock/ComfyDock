"""Typed readiness result models for portable environment handoff."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ReadinessBlockingIssue:
    """A source-state issue that blocks an immediate handoff action."""

    type: str
    message: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelSourceWarning:
    """A model entry that lacks a known download source."""

    filename: str
    hash: str | None = None
    criticality: str = "required"
    workflows: list[str] = field(default_factory=list)

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
