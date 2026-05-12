"""Typed models for dependency resolution previews."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PackageChangeKind = Literal["added", "removed", "upgraded", "downgraded", "changed"]


@dataclass(frozen=True)
class PackageVersionChange:
    """One package-level change proposed by a dependency resolver preview."""

    name: str
    current: str | None
    proposed: str | None
    kind: PackageChangeKind


@dataclass(frozen=True)
class DependencyResolutionPreview:
    """Result of simulating dependency resolution without mutating the environment."""

    success: bool
    node_name: str
    requirements: tuple[str, ...] = ()
    changes: tuple[PackageVersionChange, ...] = ()
    lockfile_changed: bool = False
    error: str | None = None
    stderr: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
    baseline_fingerprint: str = ""
    diff_fingerprint: str = ""
    proposed_fingerprint: str = ""

    @property
    def added(self) -> tuple[PackageVersionChange, ...]:
        return tuple(change for change in self.changes if change.kind == "added")

    @property
    def removed(self) -> tuple[PackageVersionChange, ...]:
        return tuple(change for change in self.changes if change.kind == "removed")

    @property
    def upgraded(self) -> tuple[PackageVersionChange, ...]:
        return tuple(change for change in self.changes if change.kind == "upgraded")

    @property
    def downgraded(self) -> tuple[PackageVersionChange, ...]:
        return tuple(change for change in self.changes if change.kind == "downgraded")


@dataclass(frozen=True)
class DependencyResolutionAcceptance:
    """User acceptance of a specific dependency preview."""

    identifier: str
    baseline_fingerprint: str
    diff_fingerprint: str
    proposed_fingerprint: str = ""


@dataclass(frozen=True)
class DependencyResolutionApplyResult:
    """Result of applying a reviewed dependency change."""

    success: bool
    identifier: str
    node_name: str
    installed: bool
    needs_restart: bool
    message: str = ""
