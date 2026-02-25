"""Import preview and analysis service."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit

from ..logging.logging_config import get_logger

if TYPE_CHECKING:
    from ..repositories.model_repository import ModelRepository
    from ..repositories.node_mappings_repository import NodeMappingsRepository

logger = get_logger(__name__)


@dataclass
class ModelAnalysis:
    """Analysis of a single model in the import."""
    filename: str
    hash: str | None
    sources: list[str]
    relative_path: str
    locally_available: bool
    needs_download: bool
    workflows: list[str]


@dataclass
class NodeAnalysis:
    """Analysis of a custom node in the import."""
    name: str
    source: str  # "registry" | "development" | "git"
    install_spec: str | None
    is_dev_node: bool


@dataclass
class WorkflowAnalysis:
    """Analysis of a workflow in the import."""
    name: str
    models_required: int
    models_optional: int


@dataclass
class ImportAnalysis:
    """Complete analysis of an import before finalization."""

    # ComfyUI version
    comfyui_version: str | None
    comfyui_version_type: str | None

    # Models breakdown
    models: list[ModelAnalysis]
    total_models: int
    models_locally_available: int
    models_needing_download: int
    models_without_sources: int

    # Nodes breakdown
    nodes: list[NodeAnalysis]
    total_nodes: int
    registry_nodes: int
    dev_nodes: int
    git_nodes: int

    # Workflows
    workflows: list[WorkflowAnalysis]
    total_workflows: int

    # Shared overlays available in the import
    overlays: list[str]
    total_overlays: int

    # Summary flags
    needs_model_downloads: bool
    needs_node_installs: bool

    def get_download_strategy_recommendation(self) -> str:
        """Recommend strategy based on analysis."""
        if self.models_without_sources > 0:
            return "required"  # Some models can't be downloaded - user must provide
        if not self.needs_model_downloads:
            return "skip"  # All models available locally
        return "all"  # Can download everything


class ImportAnalyzer:
    """Analyzes import requirements before finalization.

    Works on extracted .cec directory to provide preview of what
    will be downloaded, installed, and configured during import finalization.
    """

    def __init__(
        self,
        model_repository: ModelRepository,
        node_mapping_repository: NodeMappingsRepository
    ):
        self.model_repository = model_repository
        self.node_mapping_repository = node_mapping_repository

    def analyze_import(self, cec_path: Path) -> ImportAnalysis:
        """Analyze import requirements from extracted .cec directory.

        Args:
            cec_path: Path to extracted .cec directory

        Returns:
            ImportAnalysis with models, nodes, workflows breakdown
        """
        # Parse pyproject.toml
        pyproject_path = cec_path / "pyproject.toml"
        with open(pyproject_path, encoding='utf-8') as f:
            pyproject_data = tomlkit.load(f)

        comfygit_config = pyproject_data.get("tool", {}).get("comfygit", {})

        # Analyze models
        models = self._analyze_models(pyproject_data)

        # Analyze nodes
        nodes = self._analyze_nodes(comfygit_config)

        # Analyze workflows
        workflows = self._analyze_workflows(pyproject_data)
        overlays = self._analyze_overlays(cec_path)

        # Build summary
        return ImportAnalysis(
            comfyui_version=comfygit_config.get("comfyui_version"),
            comfyui_version_type=comfygit_config.get("comfyui_version_type"),
            models=models,
            total_models=len(models),
            models_locally_available=sum(1 for m in models if m.locally_available),
            models_needing_download=sum(1 for m in models if m.needs_download),
            models_without_sources=sum(
                1 for m in models if not m.sources and not m.locally_available
            ),
            nodes=nodes,
            total_nodes=len(nodes),
            registry_nodes=sum(1 for n in nodes if n.source == "registry"),
            dev_nodes=sum(1 for n in nodes if n.is_dev_node),
            git_nodes=sum(1 for n in nodes if n.source == "git"),
            workflows=workflows,
            total_workflows=len(workflows),
            overlays=overlays,
            total_overlays=len(overlays),
            needs_model_downloads=any(m.needs_download for m in models),
            needs_node_installs=any(n.source in ("registry", "git") for n in nodes),
        )

    def _analyze_models(self, pyproject_data: dict) -> list[ModelAnalysis]:
        """Analyze all models from pyproject.toml."""
        models = []

        # Get global models table
        global_models = pyproject_data.get("tool", {}).get("comfygit", {}).get("models", {})

        # Get all workflows
        workflows_config = pyproject_data.get("tool", {}).get("comfygit", {}).get("workflows", {})

        # Build reverse index: hash -> workflows
        hash_to_workflows = {}
        for workflow_name, workflow_data in workflows_config.items():
            for model in workflow_data.get("models", []):
                model_hash = model.get("hash")
                if model_hash:
                    hash_to_workflows.setdefault(model_hash, []).append(workflow_name)

        # Analyze each model
        for model_hash, model_data in global_models.items():
            sources = list(model_data.get("sources", []))

            # Check local availability
            existing = self.model_repository.get_model(model_hash)
            locally_available = existing is not None

            models.append(ModelAnalysis(
                filename=model_data.get("filename", "unknown"),
                hash=model_hash,
                sources=sources,
                relative_path=model_data.get("relative_path", ""),
                locally_available=locally_available,
                needs_download=not locally_available and bool(sources),
                workflows=hash_to_workflows.get(model_hash, [])
            ))

        return models

    def _analyze_nodes(self, comfygit_config: dict) -> list[NodeAnalysis]:
        """Analyze all custom nodes from pyproject.toml."""
        nodes = []
        nodes_config = comfygit_config.get("nodes", {})

        for node_name, node_data in nodes_config.items():
            source = node_data.get("source", "registry")

            nodes.append(NodeAnalysis(
                name=node_name,
                source=source,
                install_spec=node_data.get("install_spec"),
                is_dev_node=(source == "development")
            ))

        return nodes

    def _analyze_workflows(self, pyproject_data: dict) -> list[WorkflowAnalysis]:
        """Analyze all workflows."""
        workflows = []
        workflows_config = pyproject_data.get("tool", {}).get("comfygit", {}).get("workflows", {})

        for workflow_name, workflow_data in workflows_config.items():
            models = workflow_data.get("models", [])

            workflows.append(WorkflowAnalysis(
                name=workflow_name,
                models_required=sum(1 for m in models if m.get("criticality") == "required"),
                models_optional=sum(1 for m in models if m.get("criticality") == "optional"),
            ))

        return workflows

    def _analyze_overlays(self, cec_path: Path) -> list[str]:
        """List shared overlays included in import bundle."""
        overlays_path = cec_path / "overlays"
        if not overlays_path.exists():
            return []

        overlays: list[str] = []
        for overlay_path in sorted(overlays_path.glob("*.toml"), key=lambda p: p.name):
            if overlay_path.name.startswith("."):
                continue
            overlays.append(overlay_path.stem)
        return overlays
