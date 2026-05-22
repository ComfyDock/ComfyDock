# models/manifest.py
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from comfygit_core.models.shared import ModelWithLocation, NodeInfo
from comfygit_core.models.workflow import WorkflowNodeWidgetRef
from comfygit_core.models.workflow_contract import (
    WorkflowExecutionContract,
)


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item is not None)


def _readonly_mapping(items: dict[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(items))


def _plain_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
    }


def _plain_mapping_tuple(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        _readonly_mapping(_plain_mapping(item))
        for item in value
        if isinstance(item, dict)
    )


def _dependency_groups_from_toml(value: Any) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        return MappingProxyType({})
    groups = {
        str(name): _as_str_tuple(dependencies)
        for name, dependencies in value.items()
    }
    return MappingProxyType(groups)


@dataclass
class ManifestWorkflowModel:
    """Workflow model entry as stored in pyproject.toml"""
    filename: str
    category: str  # "checkpoints", "loras", etc.
    criticality: str  # "required", "flexible", "optional"
    status: str  # "resolved", "unresolved"
    nodes: list[WorkflowNodeWidgetRef]
    hash: str | None = None  # Only present if resolved
    sources: list[str] = field(default_factory=list)  # Download URLs
    relative_path: str | None = None  # Target path for download intents or manual resolved deps
    declared_by: str | None = None  # "manual" for user-declared non-graph dependencies

    def to_toml_dict(self) -> dict[str, Any]:
        """Serialize to TOML-compatible dict with inline table formatting."""
        import tomlkit

        # Build nodes as inline tables for clean TOML output
        nodes_array = tomlkit.array()
        for n in self.nodes:
            node_entry = tomlkit.inline_table()
            node_entry['node_id'] = n.node_id
            node_entry['node_type'] = n.node_type
            node_entry['widget_idx'] = n.widget_index
            node_entry['widget_value'] = n.widget_value
            nodes_array.append(node_entry)

        result: dict[str, Any] = {
            "filename": self.filename,
            "category": self.category,
            "criticality": self.criticality,
            "status": self.status,
            "nodes": nodes_array
        }

        # Only include optional fields if present
        if self.hash is not None:
            result["hash"] = self.hash
        if self.sources:
            result["sources"] = self.sources
        if self.relative_path is not None:
            result["relative_path"] = self.relative_path
        if self.declared_by is not None:
            result["declared_by"] = self.declared_by

        return result

    @classmethod
    def from_toml_dict(cls, data: dict) -> "ManifestWorkflowModel":
        """Deserialize from TOML dict."""
        nodes = [
            WorkflowNodeWidgetRef(
                node_id=n["node_id"],
                node_type=n["node_type"],
                widget_index=n["widget_idx"],
                widget_value=n["widget_value"]
            )
            for n in data.get("nodes", [])
        ]

        return cls(
            filename=data["filename"],
            category=data["category"],
            criticality=data.get("criticality", "flexible"),
            status=data.get("status", "resolved"),
            nodes=nodes,
            hash=data.get("hash"),
            sources=data.get("sources", []),
            relative_path=data.get("relative_path"),
            declared_by=data.get("declared_by")
        )


@dataclass
class ManifestModel:
    """Global model entry in [tool.comfygit.models]"""
    hash: str  # Primary key
    filename: str
    size: int
    relative_path: str
    category: str
    sources: list[str] = field(default_factory=list)

    def to_toml_dict(self) -> dict[str, Any]:
        """Serialize to TOML-compatible dict."""
        result: dict[str, Any] = {
            "filename": self.filename,
            "size": self.size,
            "relative_path": self.relative_path,
            "category": self.category
        }
        if self.sources:
            result["sources"] = self.sources
        return result

    @classmethod
    def from_toml_dict(cls, hash_key: str, data: dict) -> "ManifestModel":
        """Deserialize from TOML dict."""
        return cls(
            hash=hash_key,
            filename=data["filename"],
            size=data["size"],
            relative_path=data["relative_path"],
            category=data.get("category", "unknown"),
            sources=data.get("sources", [])
        )

    @classmethod
    def from_model_with_location(cls, model: "ModelWithLocation") -> "ManifestModel":
        """Convert runtime model to manifest entry.

        Note: Sources are intentionally empty here. They should be fetched from
        the repository and provided when creating ManifestModel instances.

        Args:
            model: ModelWithLocation from model repository

        Returns:
            ManifestModel ready for TOML serialization
        """

        return cls(
            hash=model.hash,
            filename=model.filename,
            size=model.file_size,
            relative_path=model.relative_path,
            category=model.category,
            sources=[]
        )


@dataclass(frozen=True)
class ManifestProjectSnapshot:
    """Read-only projection of standard project metadata relevant to ComfyGit."""

    name: str | None = None
    version: str | None = None
    requires_python: str | None = None
    dependencies: tuple[str, ...] = ()

    @classmethod
    def from_toml_dict(cls, data: dict[str, Any]) -> "ManifestProjectSnapshot":
        project = _plain_mapping(data.get("project", {}))
        return cls(
            name=str(project["name"]) if project.get("name") is not None else None,
            version=str(project["version"]) if project.get("version") is not None else None,
            requires_python=(
                str(project["requires-python"])
                if project.get("requires-python") is not None
                else None
            ),
            dependencies=_as_str_tuple(project.get("dependencies", [])),
        )


@dataclass(frozen=True)
class ManifestUVSnapshot:
    """Read-only projection of uv configuration stored in the manifest."""

    indexes: tuple[Mapping[str, Any], ...] = ()
    sources: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    constraints: tuple[str, ...] = ()
    exclude_dependencies: tuple[str, ...] = ()
    no_build_isolation_packages: tuple[str, ...] = ()
    override_dependencies: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()

    @classmethod
    def from_toml_dict(cls, data: dict[str, Any]) -> "ManifestUVSnapshot":
        uv_config = _plain_mapping(data.get("tool", {})).get("uv", {})
        uv = _plain_mapping(uv_config)
        return cls(
            indexes=_plain_mapping_tuple(uv.get("index", [])),
            sources=_readonly_mapping(_plain_mapping(uv.get("sources", {}))),
            constraints=_as_str_tuple(uv.get("constraint-dependencies", [])),
            exclude_dependencies=_as_str_tuple(uv.get("exclude-dependencies", [])),
            no_build_isolation_packages=_as_str_tuple(
                uv.get("no-build-isolation-package", [])
            ),
            override_dependencies=_as_str_tuple(uv.get("override-dependencies", [])),
            environments=_as_str_tuple(uv.get("environments", [])),
        )


@dataclass(frozen=True)
class ManifestWorkflowEntry:
    """Read-only projection of one `[tool.comfygit.workflows.<name>]` entry."""

    name: str
    path: str | None = None
    node_packs: tuple[str, ...] = ()
    custom_node_map: Mapping[str, str | bool] = field(default_factory=lambda: MappingProxyType({}))
    models: tuple[ManifestWorkflowModel, ...] = ()
    execution_contract: WorkflowExecutionContract | None = None

    @property
    def has_execution_contract(self) -> bool:
        return self.execution_contract is not None and self.execution_contract.has_contract

    @classmethod
    def from_toml_dict(cls, name: str, data: dict[str, Any]) -> "ManifestWorkflowEntry":
        custom_node_map = {
            str(node_type): value
            for node_type, value in _plain_mapping(data.get("custom_node_map", {})).items()
            if isinstance(value, str | bool)
        }
        models = tuple(
            ManifestWorkflowModel.from_toml_dict(model)
            for model in data.get("models", [])
            if isinstance(model, dict)
        )
        contract_data = data.get("execution_contract")
        execution_contract = (
            WorkflowExecutionContract.from_toml_dict(contract_data)
            if isinstance(contract_data, dict)
            else None
        )
        return cls(
            name=name,
            path=str(data["path"]) if data.get("path") is not None else None,
            node_packs=_as_str_tuple(data.get("nodes", [])),
            custom_node_map=MappingProxyType(custom_node_map),
            models=models,
            execution_contract=execution_contract,
        )


@dataclass(frozen=True)
class EnvironmentManifestSnapshot:
    """Typed read-only projection of the current ComfyGit manifest."""

    project: ManifestProjectSnapshot
    schema_version: int
    comfyui_version: str | None
    python_version: str | None
    manifest_state: str
    sync_extras: tuple[str, ...]
    dependency_groups: Mapping[str, tuple[str, ...]]
    uv: ManifestUVSnapshot
    nodes: Mapping[str, NodeInfo]
    workflows: Mapping[str, ManifestWorkflowEntry]
    models: Mapping[str, ManifestModel]

    def get_node(self, identifier: str) -> NodeInfo | None:
        """Return one manifest node by package identifier."""
        return self.nodes.get(identifier)

    def get_workflow(self, name: str) -> ManifestWorkflowEntry | None:
        """Return one manifest workflow entry by workflow name."""
        return self.workflows.get(name)

    def get_model(self, model_hash: str) -> ManifestModel | None:
        """Return one global manifest model by hash."""
        return self.models.get(model_hash)

    def get_workflow_models(self, workflow_name: str) -> tuple[ManifestWorkflowModel, ...]:
        """Return models declared for a workflow, or an empty tuple."""
        workflow = self.get_workflow(workflow_name)
        return workflow.models if workflow is not None else ()

    def get_workflow_custom_node_map(self, workflow_name: str) -> Mapping[str, str | bool]:
        """Return workflow-specific custom-node mappings, or an empty mapping."""
        workflow = self.get_workflow(workflow_name)
        if workflow is None:
            return MappingProxyType({})
        return workflow.custom_node_map

    @classmethod
    def from_toml_dict(cls, data: dict[str, Any]) -> "EnvironmentManifestSnapshot":
        tool = _plain_mapping(data.get("tool", {}))
        comfygit = _plain_mapping(tool.get("comfygit", {}))

        nodes_data = _plain_mapping(comfygit.get("nodes", {}))
        nodes: dict[str, NodeInfo] = {}
        for identifier in nodes_data:
            node = NodeInfo.from_pyproject_config(nodes_data, identifier)
            if node is not None:
                nodes[str(identifier)] = node

        workflows_data = _plain_mapping(comfygit.get("workflows", {}))
        workflows = {
            str(name): ManifestWorkflowEntry.from_toml_dict(str(name), workflow_data)
            for name, workflow_data in workflows_data.items()
            if isinstance(workflow_data, dict)
        }

        models_data = _plain_mapping(comfygit.get("models", {}))
        models = {
            str(hash_key): ManifestModel.from_toml_dict(str(hash_key), model_data)
            for hash_key, model_data in models_data.items()
            if isinstance(model_data, dict)
        }

        schema_version = comfygit.get("schema_version", 1)
        try:
            normalized_schema_version = int(schema_version)
        except (TypeError, ValueError):
            normalized_schema_version = 1

        return cls(
            project=ManifestProjectSnapshot.from_toml_dict(data),
            schema_version=normalized_schema_version,
            comfyui_version=(
                str(comfygit["comfyui_version"])
                if comfygit.get("comfyui_version") is not None
                else None
            ),
            python_version=(
                str(comfygit["python_version"])
                if comfygit.get("python_version") is not None
                else None
            ),
            manifest_state=str(comfygit.get("manifest_state", "local")),
            sync_extras=_as_str_tuple(_plain_mapping(comfygit.get("sync", {})).get("extras", [])),
            dependency_groups=_dependency_groups_from_toml(data.get("dependency-groups", {})),
            uv=ManifestUVSnapshot.from_toml_dict(data),
            nodes=MappingProxyType(nodes),
            workflows=MappingProxyType(workflows),
            models=MappingProxyType(models),
        )
