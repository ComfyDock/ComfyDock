"""Workflow dependency analysis and resolution manager."""
from __future__ import annotations

from pathlib import Path
from typing import Any, List

from comfygit_core.repositories.workflow_repository import WorkflowRepository

from ..logging.logging_config import get_logger
from .node_classifier import NodeClassifier
from ..configs.model_config import ModelConfig
from ..configs.comfyui_models import MULTI_MODEL_WIDGET_CONFIGS
from ..models.workflow import (
    Workflow,
    WorkflowNodeWidgetRef,
    WorkflowNode,
    WorkflowDependencies,
)

logger = get_logger(__name__)

class WorkflowDependencyParser:
    """Manages workflow dependency analysis and resolution."""

    def __init__(
        self,
        workflow: Workflow | Path,
        workflow_name: str | None = None,
        model_config: ModelConfig | None = None,
        cec_path: Path | None = None
    ):
        self.model_config = model_config or ModelConfig.load()
        self.cec_path = cec_path

        # Accept either Workflow object or Path
        if isinstance(workflow, Path):
            self.workflow = WorkflowRepository.load(workflow)
            self.workflow_name = workflow_name or workflow.stem
            logger.debug(f"Loaded workflow '{self.workflow_name}' from path with {len(self.workflow.nodes)} nodes")
        else:
            self.workflow = workflow
            self.workflow_name = workflow_name or "unnamed"
            logger.debug(f"Loaded workflow '{self.workflow_name}' from object with {len(self.workflow.nodes)} nodes")

    def analyze_dependencies(self) -> WorkflowDependencies:
        """Analyze workflow for model information and node types"""
        try:
            nodes_data = self.workflow.nodes

            if not nodes_data:
                logger.warning("No nodes found in workflow")
                return WorkflowDependencies(workflow_name=self.workflow_name)
            
            found_models: list[WorkflowNodeWidgetRef] = []
            builtin_nodes: list[WorkflowNode] = []
            missing_nodes: list[WorkflowNode] = []

            # Create classifier with environment-specific builtins
            classifier = NodeClassifier(self.cec_path)

            # Analyze and resolve models and nodes
            # Iterate over items() to preserve scoped IDs for subgraph nodes
            for node_id, node_info in nodes_data.items():
                node_classification = classifier.classify_single_node(node_info)
                model_refs = self._extract_model_node_refs(node_id, node_info)
                
                found_models.extend(model_refs)
                
                if node_classification == 'builtin':
                    builtin_nodes.append(node_info)
                else:
                    missing_nodes.append(node_info)
                    
            # Log results
            if found_models:
                logger.debug(f"Found {len(found_models)} model references in workflow")
            if builtin_nodes:
                logger.debug(f"Found {len(builtin_nodes)} builtin nodes in workflow")
            if missing_nodes:
                logger.debug(f"Found {len(missing_nodes)} missing nodes in workflow")
                
            return WorkflowDependencies(
                workflow_name=self.workflow_name,
                found_models=found_models,
                builtin_nodes=builtin_nodes,
                non_builtin_nodes=missing_nodes
            )

        except Exception as e:
            logger.error(f"Failed to analyze workflow dependencies: {e}")
            return WorkflowDependencies(workflow_name=self.workflow_name)

    def _extract_model_node_refs(self, node_id: str, node_info: WorkflowNode) -> List["WorkflowNodeWidgetRef"]:
        """Extract possible model references from a single node.

        Uses a two-pronged approach:
        1. Extract from properties.models (preferred - has URLs for auto-download)
        2. Fall back to widget extraction using MULTI_MODEL_WIDGET_CONFIGS

        Args:
            node_id: Scoped node ID from workflow.nodes dict key (e.g., "uuid:12" for subgraph nodes)
            node_info: WorkflowNode object containing node data
        """
        refs: list[WorkflowNodeWidgetRef] = []

        # Strategy 1: Extract from properties.models (preferred - has URLs)
        property_models = node_info.properties.get('models', [])
        if property_models:
            refs.extend(self._extract_from_properties_models(node_id, node_info, property_models))

        # Strategy 2: Multi-model nodes (explicit widget indices from config)
        if node_info.type in MULTI_MODEL_WIDGET_CONFIGS:
            widget_refs = self._extract_multi_model_widgets(node_id, node_info)
            refs = self._merge_model_refs(refs, widget_refs)

        # Strategy 3: Standard single-model loaders
        elif self.model_config.is_model_loader_node(node_info.type):
            widget_refs = self._extract_single_model_widget(node_id, node_info)
            refs = self._merge_model_refs(refs, widget_refs)

        # Strategy 4: Pattern match all widgets for custom nodes
        else:
            widget_refs = self._extract_by_pattern(node_id, node_info)
            refs = self._merge_model_refs(refs, widget_refs)

        return refs

    def _extract_from_properties_models(
        self,
        node_id: str,
        node_info: WorkflowNode,
        property_models: list[dict]
    ) -> list[WorkflowNodeWidgetRef]:
        """Extract model refs from node.properties.models array.

        Properties models have structure:
        {"name": "model.safetensors", "url": "https://...", "directory": "text_encoders"}
        """
        refs = []
        for idx, model_entry in enumerate(property_models):
            if not isinstance(model_entry, dict):
                continue
            name = model_entry.get('name', '')
            if not name:
                continue

            # Find corresponding widget index by matching name to widgets_values
            widget_idx = self._find_widget_index_for_name(node_info, name)

            refs.append(WorkflowNodeWidgetRef(
                node_id=node_id,
                node_type=node_info.type,
                widget_index=widget_idx if widget_idx is not None else idx,
                widget_value=name,
                property_url=model_entry.get('url'),
                property_directory=model_entry.get('directory')
            ))
        return refs

    def _find_widget_index_for_name(self, node_info: WorkflowNode, name: str) -> int | None:
        """Find widget index that contains the given model name."""
        widgets = node_info.widgets_values or []
        for idx, value in enumerate(widgets):
            if isinstance(value, str) and value == name:
                return idx
        return None

    def _extract_multi_model_widgets(self, node_id: str, node_info: WorkflowNode) -> list[WorkflowNodeWidgetRef]:
        """Extract models from multi-model nodes using MULTI_MODEL_WIDGET_CONFIGS.

        Note: Unlike pattern matching, multi-model configs explicitly define which
        widgets contain models, so we trust them without extension filtering.
        This allows CheckpointLoader to capture both .safetensors and .yaml configs.
        """
        refs = []
        widget_indices = MULTI_MODEL_WIDGET_CONFIGS.get(node_info.type, [])
        widgets = node_info.widgets_values or []

        for widget_idx in widget_indices:
            if widget_idx < len(widgets) and widgets[widget_idx]:
                value = widgets[widget_idx]
                if isinstance(value, str) and value.strip():
                    refs.append(WorkflowNodeWidgetRef(
                        node_id=node_id,
                        node_type=node_info.type,
                        widget_index=widget_idx,
                        widget_value=value
                    ))
        return refs

    def _extract_single_model_widget(self, node_id: str, node_info: WorkflowNode) -> list[WorkflowNodeWidgetRef]:
        """Extract model from standard single-model loader nodes."""
        refs = []
        widget_idx = self.model_config.get_widget_index_for_node(node_info.type)
        widgets = node_info.widgets_values or []

        if widget_idx < len(widgets) and widgets[widget_idx]:
            refs.append(WorkflowNodeWidgetRef(
                node_id=node_id,
                node_type=node_info.type,
                widget_index=widget_idx,
                widget_value=widgets[widget_idx]
            ))
        return refs

    def _extract_by_pattern(self, node_id: str, node_info: WorkflowNode) -> list[WorkflowNodeWidgetRef]:
        """Extract models by pattern matching widget values (for custom nodes)."""
        refs = []
        widgets = node_info.widgets_values or []

        for idx, value in enumerate(widgets):
            if self._looks_like_model(value):
                refs.append(WorkflowNodeWidgetRef(
                    node_id=node_id,
                    node_type=node_info.type,
                    widget_index=idx,
                    widget_value=value
                ))
        return refs

    def _merge_model_refs(
        self,
        property_refs: list[WorkflowNodeWidgetRef],
        widget_refs: list[WorkflowNodeWidgetRef]
    ) -> list[WorkflowNodeWidgetRef]:
        """Merge property refs with widget refs, preserving property metadata.

        Property refs take precedence when both have the same widget_value,
        since they may contain URL metadata for auto-download.
        """
        # Build set of values already in property_refs
        property_values = {ref.widget_value for ref in property_refs}

        # Add widget refs that aren't already covered by property refs
        merged = list(property_refs)
        for ref in widget_refs:
            if ref.widget_value not in property_values:
                merged.append(ref)

        return merged
    
    def _looks_like_model(self, value: Any) -> bool:
        """Check if value looks like a model path"""
        if not isinstance(value, str):
            return False
        extensions = self.model_config.default_extensions
        return any(value.endswith(ext) for ext in extensions)
