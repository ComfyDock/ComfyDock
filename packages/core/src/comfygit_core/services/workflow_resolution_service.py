"""Standalone workflow resolution service."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..analyzers.node_classifier import NodeClassifier
from ..logging.logging_config import get_logger
from ..models.workflow import (
    ModelResolutionContext,
    NodeResolutionContext,
    ResolutionResult,
    ResolvedModel,
    ResolvedNodePackage,
    WorkflowDependencies,
    WorkflowNode,
    WorkflowNodeWidgetRef,
)
from ..resolvers.global_node_resolver import GlobalNodeResolver
from ..resolvers.model_resolver import ModelResolver

if TYPE_CHECKING:
    from ..repositories.comfyui_builtin_versions_repository import (
        ComfyUIBuiltinVersionsRepository,
    )

logger = get_logger(__name__)


@dataclass
class ResolutionContext:
    """Context for standalone resolution (replaces environment state)."""

    installed_packages: dict[str, Any] = field(default_factory=dict)
    custom_node_mappings: dict[str, str | bool] = field(default_factory=dict)
    previous_model_resolutions: dict[WorkflowNodeWidgetRef, Any] = field(default_factory=dict)
    global_models: dict[str, Any] = field(default_factory=dict)
    cec_path: Path | None = None
    builtin_versions_repository: ComfyUIBuiltinVersionsRepository | None = None
    workflow_name: str = ""
    auto_select_ambiguous: bool = True


class WorkflowResolutionService:
    """Standalone workflow resolution — no environment required."""

    def __init__(
        self,
        global_node_resolver: GlobalNodeResolver,
        model_resolver: ModelResolver,
    ) -> None:
        self.global_node_resolver = global_node_resolver
        self.model_resolver = model_resolver

    def resolve(
        self,
        analysis: WorkflowDependencies,
        context: ResolutionContext | None = None,
    ) -> ResolutionResult:
        """Core resolution logic extracted from WorkflowManager.resolve_workflow()."""
        context = context or ResolutionContext()

        nodes_resolved: list[ResolvedNodePackage] = []
        nodes_version_gated: list[WorkflowNode] = []
        nodes_uninstallable: list[ResolvedNodePackage] = []
        nodes_unresolved: list[WorkflowNode] = []
        nodes_ambiguous: list[list[ResolvedNodePackage]] = []
        node_guidance: dict[str, str] = {}

        models_resolved: list[ResolvedModel] = []
        models_unresolved: list[WorkflowNodeWidgetRef] = []
        models_ambiguous: list[list[ResolvedModel]] = []

        workflow_name = context.workflow_name or analysis.workflow_name
        node_classifier = NodeClassifier(
            context.cec_path,
            builtin_versions_repository=context.builtin_versions_repository,
        )

        version_gated_types: set[str] = set()

        def add_version_gated(node: WorkflowNode) -> None:
            if node.type not in version_gated_types:
                nodes_version_gated.append(node)
                version_gated_types.add(node.type)

            if node.type in node_guidance:
                return

            gate_info = node_classifier.get_version_gate_info(node.type)
            if gate_info:
                node_guidance[node.type] = gate_info.message
            else:
                node_guidance[node.type] = (
                    f"Node {node.type} may require a newer ComfyUI version."
                )

        for node in analysis.version_gated_nodes:
            add_version_gated(node)

        node_context = NodeResolutionContext(
            installed_packages=context.installed_packages,
            custom_mappings=context.custom_node_mappings,
            workflow_name=workflow_name,
            auto_select_ambiguous=context.auto_select_ambiguous,
        )

        # Deduplicate node types (same type appears multiple times in workflow)
        # Prefer nodes with properties when deduplicating
        unique_nodes: dict[str, WorkflowNode] = {}
        for node in analysis.non_builtin_nodes:
            if node.type not in unique_nodes:
                unique_nodes[node.type] = node
            else:
                # Prefer node with properties over one without
                if node.properties.get("cnr_id") and not unique_nodes[node.type].properties.get("cnr_id"):
                    unique_nodes[node.type] = node

        logger.debug(
            "Resolving %s unique node types from %s total non-builtin nodes",
            len(unique_nodes),
            len(analysis.non_builtin_nodes),
        )

        for _node_type, node in unique_nodes.items():
            logger.debug("Trying to resolve node: %s", node)
            resolved_packages = self.global_node_resolver.resolve_single_node_with_context(node, node_context)

            if resolved_packages is None:
                logger.debug("Node not found: %s", node)
                nodes_unresolved.append(node)
            elif len(resolved_packages) == 1:
                candidate = resolved_packages[0]
                is_installed_candidate = bool(
                    candidate.package_id and candidate.package_id in context.installed_packages
                )
                if is_installed_candidate:
                    logger.debug(
                        "Resolved node via installed package despite manager-only mapping metadata: %s",
                        candidate,
                    )
                    nodes_resolved.append(candidate)
                elif candidate.is_manager_only_uninstallable:
                    gate_info = node_classifier.get_version_gate_info(node.type)
                    if gate_info:
                        add_version_gated(node)
                        node_guidance[node.type] = gate_info.message
                    else:
                        logger.debug("Uninstallable manager-only node match: %s", candidate)
                        nodes_uninstallable.append(candidate)
                        pkg_id = candidate.package_id or "unknown-package"
                        node_guidance[node.type] = (
                            f"Node {node.type} matched manager-only mapping "
                            f"'{pkg_id}' with no installable versions."
                        )
                else:
                    logger.debug("Resolved node: %s", candidate)
                    nodes_resolved.append(candidate)
            else:
                installable_candidates = [
                    pkg for pkg in resolved_packages if not pkg.is_manager_only_uninstallable
                ]

                if len(installable_candidates) == 1:
                    nodes_resolved.append(installable_candidates[0])
                elif len(installable_candidates) > 1:
                    nodes_ambiguous.append(installable_candidates)
                else:
                    selected = min(resolved_packages, key=lambda x: x.rank or 999)
                    gate_info = node_classifier.get_version_gate_info(node.type)
                    if gate_info:
                        add_version_gated(node)
                        node_guidance[node.type] = gate_info.message
                    else:
                        nodes_uninstallable.append(selected)
                        pkg_id = selected.package_id or "unknown-package"
                        node_guidance[node.type] = (
                            f"Node {node.type} matched manager-only mapping "
                            f"'{pkg_id}' with no installable versions."
                        )

        model_context = ModelResolutionContext(
            workflow_name=workflow_name,
            previous_resolutions=context.previous_model_resolutions,
            global_models=context.global_models,
            auto_select_ambiguous=context.auto_select_ambiguous,
        )

        # Deduplicate model refs by (widget_value, node_type) before resolving
        model_groups: dict[tuple[str, str], list[WorkflowNodeWidgetRef]] = {}
        for model_ref in analysis.found_models:
            key = (model_ref.widget_value, model_ref.node_type)
            if key not in model_groups:
                model_groups[key] = []
            model_groups[key].append(model_ref)

        for (_widget_value, _node_type), refs_in_group in model_groups.items():
            primary_ref = refs_in_group[0]
            result = self.model_resolver.resolve_model(primary_ref, model_context)

            if result is None:
                logger.debug("Failed to resolve model: %s", primary_ref)
                models_unresolved.append(primary_ref)
            elif len(result) == 1:
                resolved_model = result[0]
                logger.debug("Resolved model: %s", resolved_model)
                models_resolved.append(resolved_model)
            elif len(result) > 1:
                logger.debug("Ambiguous model: %s", result)
                models_ambiguous.append(result)
            else:
                logger.debug("Failed to resolve model: %s, result: %s", primary_ref, result)
                models_unresolved.append(primary_ref)

        return ResolutionResult(
            workflow_name=workflow_name,
            nodes_resolved=nodes_resolved,
            nodes_version_gated=nodes_version_gated,
            nodes_uninstallable=nodes_uninstallable,
            nodes_unresolved=nodes_unresolved,
            nodes_ambiguous=nodes_ambiguous,
            node_guidance=node_guidance,
            models_resolved=models_resolved,
            models_unresolved=models_unresolved,
            models_ambiguous=models_ambiguous,
        )
