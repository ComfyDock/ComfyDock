"""Typed build-readiness projections for cloud/runtime planners."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

BuildDependencyKind = Literal["python_package", "custom_node", "model"]
BuildDependencyStatus = Literal[
    "available_cached",
    "available_source",
    "available_registry",
    "missing_optional",
    "blocked_missing_source",
    "blocked_unverified",
    "blocked_incompatible",
]
BuildReadinessStatus = Literal["ready", "blocked", "failed"]


class BuildAssetCatalog(Protocol):
    """Lookup interface for platform-managed model/content catalog state."""

    def lookup_by_hash(
        self,
        *,
        content_hash: str,
        category: str | None = None,
    ) -> Mapping[str, Any] | None:
        """Return cached asset metadata when this content already exists."""


class BuildSourceValidationResult(Protocol):
    """Source-validation result shape accepted by build-readiness checks."""

    status: str
    detail: str

    def to_dict(self) -> dict[str, Any]: ...


class BuildSourceValidator(Protocol):
    """Optional source validation hook supplied by Cloud/runtime adapters."""

    def validate_source(
        self,
        *,
        source: str,
        kind: str,
        metadata: Mapping[str, Any],
    ) -> BuildSourceValidationResult: ...


@dataclass(frozen=True)
class BuildWorkflowContractIOSummary:
    """Small public summary of one workflow contract input or output."""

    name: str
    type: str | None = None
    required: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name}
        if self.type is not None:
            payload["type"] = self.type
        if self.required is not None:
            payload["required"] = self.required
        return payload


@dataclass(frozen=True)
class BuildWorkflowContractSummary:
    """Build-facing summary of the active workflow execution contract."""

    version: int | None = None
    default_contract: str = "default"
    input_count: int = 0
    output_count: int = 0
    inputs: tuple[BuildWorkflowContractIOSummary, ...] = ()
    outputs: tuple[BuildWorkflowContractIOSummary, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "default_contract": self.default_contract,
            "input_count": self.input_count,
            "output_count": self.output_count,
            "inputs": [item.to_dict() for item in self.inputs],
            "outputs": [item.to_dict() for item in self.outputs],
        }


@dataclass(frozen=True)
class BuildModelSummary:
    """Manifest model requirement projected for build planning."""

    filename: str | None = None
    category: str | None = None
    criticality: str = "required"
    status: str = "resolved"
    content_hash: str | None = None
    relative_path: str | None = None
    size_bytes: int | None = None
    sources: tuple[str, ...] = ()
    workflow: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "filename": self.filename,
            "category": self.category,
            "criticality": self.criticality,
            "status": self.status,
            "hash": self.content_hash,
            "content_hash": self.content_hash,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sources": list(self.sources),
        }
        return {key: value for key, value in payload.items() if value not in (None, [])}


@dataclass(frozen=True)
class BuildWorkflowSummary:
    """Manifest workflow requirement projected for build planning."""

    name: str
    path: str | None = None
    nodes: tuple[str, ...] = ()
    models: tuple[BuildModelSummary, ...] = ()
    execution_contract: BuildWorkflowContractSummary = field(
        default_factory=BuildWorkflowContractSummary
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "nodes": list(self.nodes),
            "models": [model.to_dict() for model in self.models],
            "execution_contract": self.execution_contract.to_dict(),
        }


@dataclass(frozen=True)
class BuildCustomNodeSummary:
    """Manifest custom-node package projected for build planning."""

    identifier: str
    name: str
    source: str = "unknown"
    required: bool = True
    criticality: str = "required"
    registry_id: str | None = None
    repository: str | None = None
    download_url: str | None = None
    version: str | None = None
    pinned_commit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "identifier": self.identifier,
            "name": self.name,
            "source": self.source,
            "required": self.required,
            "criticality": self.criticality,
            "registry_id": self.registry_id,
            "repository": self.repository,
            "download_url": self.download_url,
            "version": self.version,
            "pinned_commit": self.pinned_commit,
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class BuildDependencyProof:
    """One dependency availability proof item for build/materialization planning."""

    kind: BuildDependencyKind
    name: str
    status: BuildDependencyStatus
    required: bool = True
    source: str | None = None
    content_hash: str | None = None
    category: str | None = None
    workflow: str | None = None
    detail: str | None = None
    cache_hit: Mapping[str, Any] | None = None
    source_validation: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "required": self.required,
            "source": self.source,
            "content_hash": self.content_hash,
            "category": self.category,
            "workflow": self.workflow,
            "detail": self.detail,
            "cache_hit": dict(self.cache_hit) if self.cache_hit is not None else None,
            "source_validation": (
                dict(self.source_validation)
                if self.source_validation is not None
                else None
            ),
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class BuildReadiness:
    """Core-owned manifest dependency readiness for build/runtime planners."""

    status: BuildReadinessStatus
    environment_name: str
    python_version: str | None
    comfyui_version: str | None
    workflows: tuple[BuildWorkflowSummary, ...] = ()
    custom_nodes: tuple[BuildCustomNodeSummary, ...] = ()
    python_dependencies: tuple[str, ...] = ()
    dependency_proof: tuple[BuildDependencyProof, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "environment_name": self.environment_name,
            "python_version": self.python_version,
            "comfyui_version": self.comfyui_version,
            "workflows": [workflow.to_dict() for workflow in self.workflows],
            "custom_nodes": [node.to_dict() for node in self.custom_nodes],
            "python_dependencies": list(self.python_dependencies),
            "dependency_proof": [proof.to_dict() for proof in self.dependency_proof],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }
