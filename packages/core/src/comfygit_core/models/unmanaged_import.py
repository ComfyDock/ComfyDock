"""Typed results for unmanaged ComfyUI import scanning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol


class UnmanagedImportCallbacks(Protocol):
    """Progress callback surface for unmanaged ComfyUI imports."""

    def on_phase(self, phase: str, description: str) -> None: ...
    def on_workflow_copied(self, workflow_name: str) -> None: ...
    def on_node_installed(self, node_name: str) -> None: ...
    def on_error(self, error: str) -> None: ...


class NodeRegistryLookup(Protocol):
    """Registry package lookup surface used by unmanaged ComfyUI scanning."""

    def get_package(self, package_id: str) -> Any | None: ...
    def resolve_github_url(self, github_url: str) -> Any | None: ...


@dataclass(frozen=True)
class UnmanagedDevelopmentNodeLink:
    """Development node that should be linked into the imported environment."""

    identifier: str
    source_path: Path
    name: str | None = None


@dataclass(frozen=True)
class UnmanagedWorkflowScan:
    name: str
    path: str
    models_required: int = 0
    models_optional: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UnmanagedModelReferenceScan:
    filename: str
    workflow: str
    category: str | None = None
    relative_path: str | None = None
    widget_value: str | None = None
    node_type: str | None = None
    widget_index: int | None = None
    source_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UnmanagedCustomNodeScan:
    name: str
    path: str
    source_type: str
    registry_id: str | None = None
    version: str | None = None
    install_spec: str | None = None
    repository: str | None = None
    branch: str | None = None
    pinned_commit: str | None = None
    warning: str | None = None
    provenance_detail: str | None = None
    requires_review: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UnmanagedComfyUIImportPreview:
    source_path: str
    python_version: str
    comfyui_version: str | None
    comfyui_commit: str | None
    workflows: list[UnmanagedWorkflowScan] = field(default_factory=list)
    model_references: list[UnmanagedModelReferenceScan] = field(default_factory=list)
    models_scanned: bool = True
    custom_nodes: list[UnmanagedCustomNodeScan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_workflows(self) -> int:
        return len(self.workflows)

    @property
    def total_custom_nodes(self) -> int:
        return len(self.custom_nodes)

    @property
    def total_model_references(self) -> int:
        return len(self.model_references)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["total_workflows"] = self.total_workflows
        data["total_model_references"] = self.total_model_references
        data["total_custom_nodes"] = self.total_custom_nodes
        return data


@dataclass(frozen=True)
class UnmanagedComfyUIImportResult:
    environment_name: str
    workflows_copied: int
    custom_nodes_copied: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
