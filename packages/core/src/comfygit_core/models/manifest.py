# models/manifest.py
from dataclasses import dataclass, field
from typing import Any

from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.models.workflow import WorkflowNodeWidgetRef


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
    relative_path: str | None = None  # Target path for download intents

    def to_toml_dict(self) -> dict:
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

        result = {
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
            relative_path=data.get("relative_path")
        )


@dataclass
class WorkflowContractInput:
    """Portable execution-contract input item stored under a workflow entry."""

    name: str
    type: str
    node_id: str | int
    required: bool
    display_name: str | None = None
    widget_idx: int | None = None
    field_key: str | None = None
    default: Any = None
    min: int | float | None = None
    max: int | float | None = None
    enum_values: list[str] = field(default_factory=list)
    description: str | None = None

    def to_toml_dict(self) -> dict[str, Any]:
        """Serialize to TOML-compatible dict."""
        result = {
            "name": self.name,
            "type": self.type,
            "node_id": self.node_id,
            "required": self.required,
        }
        if self.display_name is not None:
            result["display_name"] = self.display_name
        if self.widget_idx is not None:
            result["widget_idx"] = self.widget_idx
        if self.field_key is not None:
            result["field_key"] = self.field_key
        if self.default is not None:
            result["default"] = self.default
        if self.min is not None:
            result["min"] = self.min
        if self.max is not None:
            result["max"] = self.max
        if self.enum_values:
            result["enum_values"] = self.enum_values
        if self.description is not None:
            result["description"] = self.description
        return result

    @classmethod
    def from_toml_dict(cls, data: dict) -> "WorkflowContractInput":
        """Deserialize from TOML dict."""
        return cls(
            name=data["name"],
            type=data["type"],
            node_id=data["node_id"],
            required=data["required"],
            display_name=data.get("display_name"),
            widget_idx=data.get("widget_idx"),
            field_key=data.get("field_key"),
            default=data.get("default"),
            min=data.get("min"),
            max=data.get("max"),
            enum_values=list(data.get("enum_values", [])),
            description=data.get("description"),
        )


@dataclass
class WorkflowContractOutput:
    """Portable execution-contract output item stored under a workflow entry."""

    name: str
    type: str
    node_id: str | int
    display_name: str | None = None
    selector: str | None = None
    description: str | None = None

    def to_toml_dict(self) -> dict[str, Any]:
        """Serialize to TOML-compatible dict."""
        result = {
            "name": self.name,
            "type": self.type,
            "node_id": self.node_id,
        }
        if self.display_name is not None:
            result["display_name"] = self.display_name
        if self.selector is not None:
            result["selector"] = self.selector
        if self.description is not None:
            result["description"] = self.description
        return result

    @classmethod
    def from_toml_dict(cls, data: dict) -> "WorkflowContractOutput":
        """Deserialize from TOML dict."""
        return cls(
            name=data["name"],
            type=data["type"],
            node_id=data["node_id"],
            display_name=data.get("display_name"),
            selector=data.get("selector"),
            description=data.get("description"),
        )


@dataclass
class NamedWorkflowContract:
    """Named contract variant for a workflow."""

    inputs: list[WorkflowContractInput] = field(default_factory=list)
    outputs: list[WorkflowContractOutput] = field(default_factory=list)
    display_name: str | None = None
    description: str | None = None

    def to_toml_dict(self) -> dict[str, Any]:
        """Serialize to TOML-compatible dict."""
        result: dict[str, Any] = {
            "inputs": [item.to_toml_dict() for item in self.inputs],
            "outputs": [item.to_toml_dict() for item in self.outputs],
        }
        if self.display_name is not None:
            result["display_name"] = self.display_name
        if self.description is not None:
            result["description"] = self.description
        return result

    @classmethod
    def from_toml_dict(cls, data: dict) -> "NamedWorkflowContract":
        """Deserialize from TOML dict."""
        return cls(
            inputs=[WorkflowContractInput.from_toml_dict(item) for item in data.get("inputs", [])],
            outputs=[WorkflowContractOutput.from_toml_dict(item) for item in data.get("outputs", [])],
            display_name=data.get("display_name"),
            description=data.get("description"),
        )


@dataclass
class WorkflowExecutionContract:
    """Top-level portable execution contract stored under a workflow entry."""

    version: int = 1
    default_contract: str = "default"
    contracts: dict[str, NamedWorkflowContract] = field(default_factory=dict)

    def to_toml_dict(self) -> dict[str, Any]:
        """Serialize to TOML-compatible dict."""
        return {
            "version": self.version,
            "default_contract": self.default_contract,
            "contracts": {
                name: contract.to_toml_dict()
                for name, contract in self.contracts.items()
            },
        }

    @classmethod
    def from_toml_dict(cls, data: dict) -> "WorkflowExecutionContract":
        """Deserialize from TOML dict."""
        contracts_data = data.get("contracts", {})
        return cls(
            version=data.get("version", 1),
            default_contract=data.get("default_contract", "default"),
            contracts={
                name: NamedWorkflowContract.from_toml_dict(contract_data)
                for name, contract_data in contracts_data.items()
            },
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

    def to_toml_dict(self) -> dict:
        """Serialize to TOML-compatible dict."""
        result = {
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
