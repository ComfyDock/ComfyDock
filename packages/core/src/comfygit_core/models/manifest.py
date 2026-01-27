# models/manifest.py
from dataclasses import dataclass, field

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
