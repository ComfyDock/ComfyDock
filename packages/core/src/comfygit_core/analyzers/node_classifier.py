"""Node classification service for workflow analysis."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..configs.comfyui_builtin_nodes import COMFYUI_BUILTIN_NODES
from ..logging.logging_config import get_logger

if TYPE_CHECKING:
    from ..configs.model_config import ModelConfig
    from ..models.workflow import Workflow, WorkflowNode

logger = get_logger(__name__)

@dataclass
class NodeClassifierResultMulti:
    builtin_nodes: list[WorkflowNode]
    custom_nodes: list[WorkflowNode]

class NodeClassifier:
    """Service for classifying and categorizing workflow nodes."""

    def __init__(self, cec_path: Path | None = None):
        """
        Initialize node classifier with environment-specific or global builtins.

        Args:
            cec_path: Path to environment's .cec directory.
                      If provided, loads from .cec/comfyui_builtins.json.
                      If None or file missing, falls back to global config.
        """
        self.builtin_nodes = self._load_builtin_nodes(cec_path)

    def _load_builtin_nodes(self, cec_path: Path | None) -> set[str]:
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
                        return nodes
                except Exception as e:
                    logger.warning(
                        f"Failed to load environment builtin config from {builtins_file}: {e}"
                    )
                    logger.warning("Falling back to global static config")

        # Fallback to global static config
        logger.debug("Using global static builtin node config")
        return set(COMFYUI_BUILTIN_NODES["all_builtin_nodes"])

    def get_custom_node_types(self, workflow: Workflow) -> set[str]:
        """Get custom node types from workflow."""
        return workflow.node_types - self.builtin_nodes

    def get_model_loader_nodes(self, workflow: Workflow, model_config: ModelConfig) -> list[WorkflowNode]:
        """Get model loader nodes from workflow."""
        return [node for node in workflow.nodes.values() if model_config.is_model_loader_node(node.type)]

    def classify_single_node(self, node: WorkflowNode) -> str:
        """Classify a single node by type using environment-specific builtins."""
        if node.type in self.builtin_nodes:
            return "builtin"
        return "custom"

    @staticmethod
    def classify_nodes(
        workflow: Workflow,
        cec_path: Path | None = None
    ) -> NodeClassifierResultMulti:
        """Classify all nodes using environment-specific or global builtins."""
        classifier = NodeClassifier(cec_path)
        builtin_nodes: list[WorkflowNode] = []
        custom_nodes: list[WorkflowNode] = []

        for node in workflow.nodes.values():
            if classifier.classify_single_node(node) == "builtin":
                builtin_nodes.append(node)
            else:
                custom_nodes.append(node)

        return NodeClassifierResultMulti(builtin_nodes, custom_nodes)
