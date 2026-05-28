"""Node classification service for workflow analysis."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

from ..configs.comfyui_builtin_nodes import COMFYUI_BUILTIN_NODES
from ..logging.logging_config import get_logger
from ..models.comfyui_builtin_versions import BuiltinVersionGateInfo

if TYPE_CHECKING:
    from ..configs.model_config import ModelConfig
    from ..models.workflow import Workflow, WorkflowNode
    from ..repositories.comfyui_builtin_versions_repository import (
        ComfyUIBuiltinVersionsRepository,
    )

logger = get_logger(__name__)

@dataclass
class NodeClassifierResultMulti:
    builtin_nodes: list[WorkflowNode]
    custom_nodes: list[WorkflowNode]
    version_gated_nodes: list[WorkflowNode] = field(default_factory=list)


@dataclass
class NodeClassificationResult:
    classification: str  # "builtin" | "version_gated" | "custom"
    version_gate_info: BuiltinVersionGateInfo | None = None

class NodeClassifier:
    """Service for classifying and categorizing workflow nodes."""

    def __init__(
        self,
        cec_path: Path | None = None,
        builtin_versions_repository: ComfyUIBuiltinVersionsRepository | None = None,
        version_agnostic: bool = False,
    ):
        """
        Initialize node classifier with environment-specific or global builtins.

        Args:
            cec_path: Path to environment's .cec directory.
                      If provided, loads from .cec/comfyui_builtins.json.
                      If None or file missing, falls back to global config.
            builtin_versions_repository: Optional repository for version-indexed builtins.
            version_agnostic: If True, treat ALL known builtins as present regardless
                              of version. Used for standalone/web analysis where we're
                              not tied to a specific ComfyUI installation.
        """
        self.builtin_versions_repository = builtin_versions_repository
        self.version_agnostic = version_agnostic
        self.builtin_nodes, detected_version = self._load_builtin_nodes(cec_path)
        self.comfyui_version = detected_version or self._load_comfyui_version_from_pyproject(cec_path)

        # In version-agnostic mode, expand builtin_nodes to include ALL known builtins
        # so they classify as "builtin" rather than "version_gated"
        if self.version_agnostic and self.builtin_versions_repository:
            db = self.builtin_versions_repository.database
            if db:
                extra = set(db.builtins.keys()) - self.builtin_nodes
                if extra:
                    logger.debug(
                        "Version-agnostic mode: adding %d version-indexed builtins to known set",
                        len(extra),
                    )
                    self.builtin_nodes = self.builtin_nodes | extra

    def _load_builtin_nodes(self, cec_path: Path | None) -> tuple[set[str], str | None]:
        """Load builtin nodes from environment or global fallback."""
        if cec_path:
            builtins_file = cec_path / "comfyui_builtins.json"
            if builtins_file.exists():
                try:
                    with open(builtins_file, encoding='utf-8') as f:
                        data = json.load(f)
                        nodes = set(data["all_builtin_nodes"])
                        version = data.get('metadata', {}).get('comfyui_version', 'unknown')
                        logger.debug(
                            f"Loaded {len(nodes)} builtin nodes from environment "
                            f"(ComfyUI {version})"
                        )
                        return nodes, version if isinstance(version, str) else None
                except Exception as e:
                    logger.warning(
                        f"Failed to load environment builtin config from {builtins_file}: {e}"
                    )
                    logger.warning("Falling back to global static config")

        # Fallback to global static config
        logger.debug("Using global static builtin node config")
        return set(COMFYUI_BUILTIN_NODES["all_builtin_nodes"]), None

    def _load_comfyui_version_from_pyproject(self, cec_path: Path | None) -> str | None:
        """Best-effort fallback: load ComfyUI version from .cec/pyproject.toml."""
        if not cec_path:
            return None

        pyproject_path = cec_path / "pyproject.toml"
        if not pyproject_path.exists():
            return None

        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            tool = data.get("tool", {})
            comfygit = tool.get("comfygit", {})
            version = comfygit.get("comfyui_version")
            if isinstance(version, str) and version.strip():
                return version.strip()
        except Exception as e:
            logger.debug(f"Could not read comfyui_version from {pyproject_path}: {e}")

        return None

    def get_custom_node_types(self, workflow: Workflow) -> set[str]:
        """Get custom node types from workflow."""
        return workflow.node_types - self.builtin_nodes

    def get_model_loader_nodes(self, workflow: Workflow, model_config: ModelConfig) -> list[WorkflowNode]:
        """Get model loader nodes from workflow."""
        return [node for node in workflow.nodes.values() if model_config.is_model_loader_node(node.type)]

    def get_version_gate_info(self, node_type: str) -> BuiltinVersionGateInfo | None:
        """Get version-gated metadata if this node is a known builtin not present now."""
        if node_type in self.builtin_nodes:
            return None
        if self.builtin_versions_repository is None:
            return None

        info = self.builtin_versions_repository.get_version_gate_info(
            node_type=node_type,
            current_version=self.comfyui_version
        )
        if not isinstance(info, BuiltinVersionGateInfo):
            return None
        return info

    def classify_node(self, node: WorkflowNode) -> NodeClassificationResult:
        """Classify a single node with builtin/version-gated/custom semantics."""
        if node.type in self.builtin_nodes:
            return NodeClassificationResult(classification="builtin")

        version_gate_info = self.get_version_gate_info(node.type)
        if version_gate_info is not None:
            return NodeClassificationResult(
                classification="version_gated",
                version_gate_info=version_gate_info
            )

        return NodeClassificationResult(classification="custom")

    def classify_single_node(self, node: WorkflowNode) -> str:
        """Classify a single node by type using environment-specific builtins."""
        return self.classify_node(node).classification

    @staticmethod
    def classify_nodes(
        workflow: Workflow,
        cec_path: Path | None = None,
        builtin_versions_repository: ComfyUIBuiltinVersionsRepository | None = None
    ) -> NodeClassifierResultMulti:
        """Classify all nodes using environment-specific or global builtins."""
        classifier = NodeClassifier(cec_path, builtin_versions_repository)
        builtin_nodes: list[WorkflowNode] = []
        custom_nodes: list[WorkflowNode] = []
        version_gated_nodes: list[WorkflowNode] = []

        for node in workflow.nodes.values():
            classification = classifier.classify_single_node(node)
            if classification == "builtin":
                builtin_nodes.append(node)
            elif classification == "version_gated":
                version_gated_nodes.append(node)
            else:
                custom_nodes.append(node)

        return NodeClassifierResultMulti(builtin_nodes, custom_nodes, version_gated_nodes)
