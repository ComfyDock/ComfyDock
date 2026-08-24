"""Typed workspace inventory and non-destructive reclaim contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .shared import ModelLocation

RESOURCE_INVENTORY_SCHEMA_VERSION = 1
MODEL_DELETION_PLAN_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ModelSource:
    """One nonsecret recovery source associated with an indexed model."""

    type: str
    url: str
    repo_id: str | None = None
    repo_type: str | None = None
    revision: str | None = None
    resolved_revision: str | None = None
    path_in_repo: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_immutable_revision(self) -> bool:
        return bool(self.resolved_revision)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "has_immutable_revision": self.has_immutable_revision,
        }


@dataclass(frozen=True)
class EnvironmentDependency:
    """Portable dependency declared by an environment manifest."""

    kind: str
    identifier: str
    criticality: str
    workflow_names: tuple[str, ...] = ()
    content_hash: str | None = None
    relative_path: str | None = None
    source: str | None = None
    version: str | None = None
    pinned_commit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StorageSummary:
    """Physical storage observations for one materialized environment."""

    environment_bytes: int = 0
    venv_bytes: int = 0
    comfyui_bytes: int = 0
    input_bytes: int = 0
    output_bytes: int = 0
    shared_cache_bytes: int = 0
    shared_models_bytes: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class EnvironmentInventory:
    """Portable and materialized facts for one ComfyGit environment."""

    name: str
    path: str
    manifest_path: str
    manifest_sha256: str
    complete: bool
    comfyui_revision: str | None
    python_version: str | None
    model_dependencies: tuple[EnvironmentDependency, ...]
    custom_node_dependencies: tuple[EnvironmentDependency, ...]
    storage: StorageSummary

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelInventoryEntry:
    """One indexed model grouped across every physical location."""

    short_hash: str
    file_size: int
    category: str
    blake3_hash: str | None
    sha256_hash: str | None
    locations: tuple[ModelLocation, ...]
    sources: tuple[ModelSource, ...]
    referencing_environments: tuple[str, ...]

    @property
    def has_strong_hash(self) -> bool:
        return bool(self.blake3_hash or self.sha256_hash)

    @property
    def has_recovery_source(self) -> bool:
        return bool(self.sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "short_hash": self.short_hash,
            "file_size": self.file_size,
            "category": self.category,
            "blake3_hash": self.blake3_hash,
            "sha256_hash": self.sha256_hash,
            "locations": [location.to_dict() for location in self.locations],
            "sources": [source.to_dict() for source in self.sources],
            "referencing_environments": list(self.referencing_environments),
            "has_strong_hash": self.has_strong_hash,
            "has_recovery_source": self.has_recovery_source,
        }


@dataclass(frozen=True)
class WorkspaceInventory:
    """Combined public inventory document for adapter serialization."""

    workspace_path: str
    models_directory: str
    models: tuple[ModelInventoryEntry, ...]
    environments: tuple[EnvironmentInventory, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESOURCE_INVENTORY_SCHEMA_VERSION,
            "kind": "workspace_inventory",
            "workspace_path": self.workspace_path,
            "models_directory": self.models_directory,
            "models": [model.to_dict() for model in self.models],
            "environments": [environment.to_dict() for environment in self.environments],
        }


@dataclass(frozen=True)
class ModelDeletionPlan:
    """Read-only, revalidatable plan for selected model locations."""

    model: ModelInventoryEntry
    target_locations: tuple[ModelLocation, ...]
    remaining_locations: tuple[ModelLocation, ...]
    potential_reclaim_bytes: int
    selection_explicit: bool
    delete_all_locations: bool
    recovery_complete: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def can_apply(self) -> bool:
        return self.selection_explicit and not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_DELETION_PLAN_SCHEMA_VERSION,
            "kind": "model_deletion_plan",
            "model": self.model.to_dict(),
            "target_locations": [location.to_dict() for location in self.target_locations],
            "remaining_locations": [location.to_dict() for location in self.remaining_locations],
            "potential_reclaim_bytes": self.potential_reclaim_bytes,
            "selection_explicit": self.selection_explicit,
            "delete_all_locations": self.delete_all_locations,
            "recovery_complete": self.recovery_complete,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "can_apply": self.can_apply,
        }


@dataclass(frozen=True)
class ModelDeletionApplyResult:
    """Result of explicitly applying a revalidated location deletion plan."""

    model_hash: str
    deleted_paths: tuple[str, ...] = ()
    missing_paths: tuple[str, ...] = ()
    errors: tuple[dict[str, str], ...] = ()
    remaining_locations: int = 0
    reference_override: bool = False
    recovery_override: bool = False

    @property
    def status(self) -> str:
        return "partial" if self.errors else "success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_DELETION_PLAN_SCHEMA_VERSION,
            "kind": "model_deletion_result",
            **asdict(self),
            "status": self.status,
        }
