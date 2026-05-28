"""Strategy-driven workflow resolution fixing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..logging.logging_config import get_logger
from ..models.manifest import ManifestModel
from ..models.protocols import ModelResolutionStrategy, NodeResolutionStrategy
from ..models.shared import NodeInfo
from ..models.workflow import (
    ModelResolutionContext,
    NodeResolutionContext,
    ResolutionResult,
    ResolvedModel,
    WorkflowNode,
    WorkflowNodeWidgetRef,
)

if TYPE_CHECKING:
    from ..models.workflow import ResolvedNodePackage
    from .model_downloader import ModelDownloader

logger = get_logger(__name__)


class NodeManifestReaderProtocol(Protocol):
    """Custom node manifest reads needed while fixing workflow resolution."""

    def get_existing(self) -> dict[str, NodeInfo]:
        """Return currently tracked node packages."""
        ...


class WorkflowMappingManifestProtocol(Protocol):
    """Workflow manifest mapping writes needed by resolution fixing."""

    def get_custom_node_map(
        self,
        workflow_name: str,
        config: dict | None = None,
    ) -> dict[str, str | bool]:
        """Return custom node mappings for one workflow."""
        ...

    def set_custom_node_mapping(
        self,
        workflow_name: str,
        node_type: str,
        package_id: str | None,
    ) -> None:
        """Store a custom node mapping for one workflow."""
        ...


class ModelManifestReaderProtocol(Protocol):
    """Global model manifest reads needed by model strategy context."""

    def get_all(self) -> list[ManifestModel]:
        """Return tracked global manifest models."""
        ...


class WorkflowResolutionFixer:
    """Applies strategy-selected fixes with progressive manifest writes."""

    def __init__(
        self,
        *,
        nodes: NodeManifestReaderProtocol,
        workflows: WorkflowMappingManifestProtocol,
        models: ModelManifestReaderProtocol,
        search_packages: Callable[..., list],
        search_models: Callable[[str, str | None, int], list],
        downloader: ModelDownloader | None,
        consensus_custom_node_map: Callable[[str], dict[str, str | bool]],
        normalize_package_id: Callable[[str], str],
        write_single_node_resolution: Callable[[str, str], None],
        write_model_resolution_grouped: Callable[
            [str, ResolvedModel, list[WorkflowNodeWidgetRef]],
            None,
        ],
        update_workflow_model_paths: Callable[[ResolutionResult], int],
    ) -> None:
        self.nodes = nodes
        self.workflows = workflows
        self.models = models
        self.search_packages = search_packages
        self.search_models = search_models
        self.downloader = downloader
        self.consensus_custom_node_map = consensus_custom_node_map
        self.normalize_package_id = normalize_package_id
        self.write_single_node_resolution = write_single_node_resolution
        self.write_model_resolution_grouped = write_model_resolution_grouped
        self.update_workflow_model_paths = update_workflow_model_paths

    def fix_resolution(
        self,
        resolution: ResolutionResult,
        node_strategy: NodeResolutionStrategy | None = None,
        model_strategy: ModelResolutionStrategy | None = None,
    ) -> ResolutionResult:
        """Fix remaining issues using strategies with progressive writes."""
        workflow_name = resolution.workflow_name

        node_result = self._fix_nodes(
            workflow_name,
            resolution,
            node_strategy,
        )
        model_result = self._fix_models(
            workflow_name,
            resolution,
            model_strategy,
        )

        result = ResolutionResult(
            workflow_name=workflow_name,
            nodes_resolved=node_result.nodes_resolved,
            nodes_version_gated=list(resolution.nodes_version_gated),
            nodes_uninstallable=list(resolution.nodes_uninstallable),
            nodes_unresolved=node_result.nodes_unresolved,
            nodes_ambiguous=node_result.nodes_ambiguous,
            node_guidance=dict(resolution.node_guidance),
            models_resolved=model_result.models_resolved,
            models_unresolved=model_result.models_unresolved,
            models_ambiguous=model_result.models_ambiguous,
        )

        self.update_workflow_model_paths(result)
        return result

    def _fix_nodes(
        self,
        workflow_name: str,
        resolution: ResolutionResult,
        node_strategy: NodeResolutionStrategy | None,
    ) -> _NodeFixResult:
        nodes_to_add = list(resolution.nodes_resolved)
        remaining_ambiguous: list[list[ResolvedNodePackage]] = []
        remaining_unresolved: list[WorkflowNode] = []

        if not node_strategy:
            return _NodeFixResult(
                nodes_resolved=nodes_to_add,
                nodes_ambiguous=list(resolution.nodes_ambiguous),
                nodes_unresolved=list(resolution.nodes_unresolved),
            )

        node_context = NodeResolutionContext(
            installed_packages=self.nodes.get_existing(),
            custom_mappings={
                **self.consensus_custom_node_map(workflow_name),
                **self.workflows.get_custom_node_map(workflow_name),
            },
            workflow_name=workflow_name,
            search_fn=self.search_packages,
            auto_select_ambiguous=True,
        )

        for node_type, candidates in self._unresolved_node_groups(resolution):
            try:
                selected = node_strategy.resolve_unknown_node(
                    node_type,
                    candidates,
                    node_context,
                )

                if selected is None:
                    self._keep_unresolved_node(
                        node_type,
                        candidates,
                        remaining_ambiguous,
                        remaining_unresolved,
                    )
                    logger.debug(f"Skipped: {node_type}")
                    continue

                if selected.match_type == "optional":
                    if workflow_name:
                        self.workflows.set_custom_node_mapping(
                            workflow_name,
                            node_type,
                            None,
                        )
                    logger.info(f"Marked node '{node_type}' as optional")
                    continue

                nodes_to_add.append(selected)
                node_id = (
                    selected.package_data.id
                    if selected.package_data
                    else selected.package_id
                )
                if not node_id:
                    logger.warning(f"No package ID for resolved node '{node_type}'")
                    continue

                normalized_id = self.normalize_package_id(node_id)
                if selected.match_type in ("user_confirmed", "manual", "heuristic") and workflow_name:
                    self.workflows.set_custom_node_mapping(
                        workflow_name,
                        node_type,
                        normalized_id,
                    )
                    logger.info(f"Saved custom_node_map: {node_type} -> {normalized_id}")

                if workflow_name:
                    self.write_single_node_resolution(workflow_name, normalized_id)

                logger.info(f"Resolved node: {node_type} -> {normalized_id}")

            except Exception as exc:
                logger.error(f"Failed to resolve {node_type}: {exc}")
                self._keep_unresolved_node(
                    node_type,
                    candidates,
                    remaining_ambiguous,
                    remaining_unresolved,
                )

        return _NodeFixResult(
            nodes_resolved=nodes_to_add,
            nodes_ambiguous=remaining_ambiguous,
            nodes_unresolved=remaining_unresolved,
        )

    def _fix_models(
        self,
        workflow_name: str,
        resolution: ResolutionResult,
        model_strategy: ModelResolutionStrategy | None,
    ) -> _ModelFixResult:
        models_to_add = list(resolution.models_resolved)
        remaining_ambiguous: list[list[ResolvedModel]] = []
        remaining_unresolved: list[WorkflowNodeWidgetRef] = []

        if not model_strategy:
            return _ModelFixResult(
                models_resolved=models_to_add,
                models_ambiguous=list(resolution.models_ambiguous),
                models_unresolved=list(resolution.models_unresolved),
            )

        model_context = ModelResolutionContext(
            workflow_name=workflow_name,
            global_models=self._global_models_by_hash(),
            search_fn=self.search_models,
            downloader=self.downloader,
            auto_select_ambiguous=True,
        )

        for (widget_value, _node_type), group in self._unresolved_model_groups(resolution).items():
            all_refs = [ref for ref, _ in group]
            primary_ref, primary_candidates = group[0]

            if len(all_refs) > 1:
                node_ids = ", ".join(f"#{ref.node_id}" for ref in all_refs)
                logger.info(
                    f"Deduplicating model '{widget_value}' found in nodes: {node_ids}"
                )

            try:
                resolved = model_strategy.resolve_model(
                    primary_ref,
                    primary_candidates,
                    model_context,
                )

                if resolved is None:
                    remaining_unresolved.extend(all_refs)
                    logger.debug(f"Skipped: {widget_value}")
                    continue

                if workflow_name:
                    self.write_model_resolution_grouped(
                        workflow_name,
                        resolved,
                        all_refs,
                    )

                models_to_add.extend(
                    self._resolution_for_each_ref(
                        workflow_name,
                        resolved,
                        all_refs,
                    )
                )

                if resolved.is_optional:
                    logger.info(f"Marked as optional: {widget_value}")
                elif resolved.resolved_model:
                    logger.info(
                        f"Resolved: {widget_value} → {resolved.resolved_model.filename}"
                    )
                else:
                    logger.info(f"Marked as optional (unresolved): {widget_value}")

            except Exception as exc:
                logger.error(f"Failed to resolve {widget_value}: {exc}")
                remaining_unresolved.extend(all_refs)

        return _ModelFixResult(
            models_resolved=models_to_add,
            models_ambiguous=remaining_ambiguous,
            models_unresolved=remaining_unresolved,
        )

    def _global_models_by_hash(self) -> dict[str, ManifestModel]:
        global_models: dict[str, ManifestModel] = {}
        try:
            for model in self.models.get_all():
                global_models[model.hash] = model
        except Exception as exc:
            logger.warning(f"Failed to load global models table: {exc}")
        return global_models

    @staticmethod
    def _unresolved_node_groups(
        resolution: ResolutionResult,
    ) -> list[tuple[str, list[ResolvedNodePackage]]]:
        unresolved: list[tuple[str, list[ResolvedNodePackage]]] = []
        for packages in resolution.nodes_ambiguous:
            if packages:
                unresolved.append((packages[0].node_type, packages))
        for node in resolution.nodes_unresolved:
            unresolved.append((node.type, []))
        return unresolved

    @staticmethod
    def _unresolved_model_groups(
        resolution: ResolutionResult,
    ) -> dict[tuple[str, str], list[tuple[WorkflowNodeWidgetRef, list[ResolvedModel]]]]:
        unresolved: list[tuple[WorkflowNodeWidgetRef, list[ResolvedModel]]] = []
        for resolved_model_list in resolution.models_ambiguous:
            if resolved_model_list:
                unresolved.append((
                    resolved_model_list[0].reference,
                    resolved_model_list,
                ))
        for model_ref in resolution.models_unresolved:
            unresolved.append((model_ref, []))

        groups: dict[tuple[str, str], list[tuple[WorkflowNodeWidgetRef, list[ResolvedModel]]]] = {}
        for model_ref, candidates in unresolved:
            key = (model_ref.widget_value, model_ref.node_type)
            groups.setdefault(key, []).append((model_ref, candidates))
        return groups

    @staticmethod
    def _keep_unresolved_node(
        node_type: str,
        candidates: list[ResolvedNodePackage],
        remaining_ambiguous: list[list[ResolvedNodePackage]],
        remaining_unresolved: list[WorkflowNode],
    ) -> None:
        if candidates:
            remaining_ambiguous.append(candidates)
        else:
            remaining_unresolved.append(WorkflowNode(id="", type=node_type))

    @staticmethod
    def _resolution_for_each_ref(
        workflow_name: str,
        resolved: ResolvedModel,
        refs: list[WorkflowNodeWidgetRef],
    ) -> list[ResolvedModel]:
        return [
            ResolvedModel(
                workflow=workflow_name,
                reference=ref,
                resolved_model=resolved.resolved_model,
                model_source=resolved.model_source,
                is_optional=resolved.is_optional,
                match_type=resolved.match_type,
                match_confidence=resolved.match_confidence,
                target_path=resolved.target_path,
                needs_path_sync=resolved.needs_path_sync,
            )
            for ref in refs
        ]


@dataclass
class _NodeFixResult:
    nodes_resolved: list[ResolvedNodePackage]
    nodes_ambiguous: list[list[ResolvedNodePackage]]
    nodes_unresolved: list[WorkflowNode]


@dataclass
class _ModelFixResult:
    models_resolved: list[ResolvedModel]
    models_ambiguous: list[list[ResolvedModel]]
    models_unresolved: list[WorkflowNodeWidgetRef]
