"""Workflow dependency analysis and resolution manager."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from comfygit_core.repositories.workflow_repository import WorkflowRepository

from ..configs.comfyui_models import MULTI_MODEL_WIDGET_CONFIGS
from ..configs.model_config import ModelConfig, ModelLoaderWidgetMapping
from ..logging.logging_config import get_logger
from ..models.workflow import (
    NodeInput,
    Workflow,
    WorkflowDependencies,
    WorkflowNode,
    WorkflowNodeWidgetRef,
)
from .node_classifier import NodeClassifier

logger = get_logger(__name__)

if TYPE_CHECKING:
    from ..repositories.comfyui_builtin_versions_repository import (
        ComfyUIBuiltinVersionsRepository,
    )


class WorkflowDependencyParser:
    """Manages workflow dependency analysis and resolution."""

    def __init__(
        self,
        workflow: Workflow | Path,
        workflow_name: str | None = None,
        model_config: ModelConfig | None = None,
        cec_path: Path | None = None,
        builtin_versions_repository: ComfyUIBuiltinVersionsRepository | None = None,
        version_agnostic: bool = False,
    ):
        self.model_config = model_config or ModelConfig.load(cec_path=cec_path)
        self.cec_path = cec_path
        self.builtin_versions_repository = builtin_versions_repository
        self.version_agnostic = version_agnostic

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
            version_gated_nodes: list[WorkflowNode] = []
            missing_nodes: list[WorkflowNode] = []

            # Create classifier with environment-specific builtins
            classifier = NodeClassifier(
                self.cec_path,
                builtin_versions_repository=self.builtin_versions_repository,
                version_agnostic=self.version_agnostic,
            )

            # Analyze and resolve models and nodes
            # Iterate over items() to preserve scoped IDs for subgraph nodes
            for node_id, node_info in nodes_data.items():
                node_classification = classifier.classify_single_node(node_info)
                model_refs = self._extract_model_node_refs(node_id, node_info)

                found_models.extend(model_refs)

                if node_classification == 'builtin':
                    builtin_nodes.append(node_info)
                elif node_classification == 'version_gated':
                    version_gated_nodes.append(node_info)
                else:
                    missing_nodes.append(node_info)

            # Log results
            if found_models:
                logger.debug(f"Found {len(found_models)} model references in workflow")
            if builtin_nodes:
                logger.debug(f"Found {len(builtin_nodes)} builtin nodes in workflow")
            if version_gated_nodes:
                logger.debug(f"Found {len(version_gated_nodes)} version-gated builtin nodes in workflow")
            if missing_nodes:
                logger.debug(f"Found {len(missing_nodes)} missing nodes in workflow")

            return WorkflowDependencies(
                workflow_name=self.workflow_name,
                found_models=found_models,
                builtin_nodes=builtin_nodes,
                version_gated_nodes=version_gated_nodes,
                non_builtin_nodes=missing_nodes
            )

        except Exception as e:
            logger.error(f"Failed to analyze workflow dependencies: {e}")
            return WorkflowDependencies(workflow_name=self.workflow_name)

    def _extract_model_node_refs(self, node_id: str, node_info: WorkflowNode) -> list[WorkflowNodeWidgetRef]:
        """Extract possible model references from a single node.

        Uses explicit extraction strategies:
        1. Extract from properties.models (preferred - has URLs for auto-download)
        2. Extract from configured/generated model-loader widget metadata

        Args:
            node_id: Scoped node ID from workflow.nodes dict key (e.g., "uuid:12" for subgraph nodes)
            node_info: WorkflowNode object containing node data
        """
        refs: list[WorkflowNodeWidgetRef] = []

        # Strategy 1: Extract from properties.models (preferred - has URLs)
        property_models = node_info.properties.get('models', [])
        if property_models:
            refs.extend(self._extract_from_properties_models(node_id, node_info, property_models))

        # Strategy 2: Generated/static model loader widget metadata
        if self.model_config.is_model_loader_node(node_info.type):
            widget_refs = self._extract_model_loader_widgets(node_id, node_info)
            if not widget_refs:
                widget_refs = self._extract_static_fallback_widgets(node_id, node_info)
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

    def _find_widget_index_for_input_name(
        self,
        inputs: list[NodeInput],
        widget_name: str,
    ) -> int | None:
        """Find frontend widget index from ComfyUI input metadata."""
        widget_idx = 0
        for input_info in inputs:
            if input_info.link is not None:
                continue

            widget_metadata = input_info.widget or {}
            if widget_metadata:
                candidate_names = {input_info.name}
                metadata_name = widget_metadata.get("name")
                if isinstance(metadata_name, str):
                    candidate_names.add(metadata_name)

                if widget_name in candidate_names:
                    return widget_idx

                widget_idx += 1

        return None

    def _resolve_model_widget_index(
        self,
        node_info: WorkflowNode,
        mapping: ModelLoaderWidgetMapping,
        mapping_count: int,
    ) -> int | None:
        if mapping.widget_name:
            index = self._find_widget_index_for_input_name(
                node_info.inputs,
                mapping.widget_name,
            )
            if index is not None:
                return index

        if mapping.widget_index is not None:
            return mapping.widget_index

        widgets = node_info.widgets_values or []
        if mapping_count == 1 and len(widgets) == 1:
            return 0

        return None

    def _extract_model_loader_widgets(
        self,
        node_id: str,
        node_info: WorkflowNode,
    ) -> list[WorkflowNodeWidgetRef]:
        """Extract model refs from configured/generated model loader widgets."""
        refs: list[WorkflowNodeWidgetRef] = []
        mappings = self.model_config.get_model_loader_widgets(node_info.type)
        widgets = node_info.widgets_values or []

        for mapping in mappings:
            widget_idx = self._resolve_model_widget_index(
                node_info,
                mapping,
                len(mappings),
            )
            if widget_idx is None or widget_idx >= len(widgets):
                continue

            value = widgets[widget_idx]
            if not isinstance(value, str) or not value.strip():
                continue

            refs.append(WorkflowNodeWidgetRef(
                node_id=node_id,
                node_type=node_info.type,
                widget_index=widget_idx,
                widget_value=value,
                property_directory=mapping.directories[0] if mapping.directories else None,
            ))

        return refs

    def _extract_static_fallback_widgets(
        self,
        node_id: str,
        node_info: WorkflowNode,
    ) -> list[WorkflowNodeWidgetRef]:
        """Fallback for workflows without frontend input widget metadata."""
        refs: list[WorkflowNodeWidgetRef] = []
        widgets = node_info.widgets_values or []
        widget_indices = MULTI_MODEL_WIDGET_CONFIGS.get(
            node_info.type,
            [self.model_config.get_widget_index_for_node(node_info.type)],
        )
        directories = self.model_config.get_directories_for_node(node_info.type)

        for widget_idx in widget_indices:
            if widget_idx >= len(widgets):
                continue
            value = widgets[widget_idx]
            if not isinstance(value, str) or not value.strip():
                continue
            refs.append(
                WorkflowNodeWidgetRef(
                    node_id=node_id,
                    node_type=node_info.type,
                    widget_index=widget_idx,
                    widget_value=value,
                    property_directory=directories[0] if directories else None,
                )
            )

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
