"""Manifest writeback for workflow resolution results."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..logging.logging_config import get_logger
from ..models.manifest import ManifestModel, ManifestWorkflowModel
from ..models.workflow import ResolutionResult, ResolvedModel, WorkflowNodeWidgetRef

if TYPE_CHECKING:
    from ..managers.pyproject_manager import PyprojectManager

logger = get_logger(__name__)


class WorkflowManifestReconciler:
    """Owns conversion from workflow resolution results to manifest edits."""

    def __init__(
        self,
        *,
        pyproject: PyprojectManager,
        model_repository: Any,
        normalize_package_id: Callable[[str], str],
        category_for_node_ref: Callable[[WorkflowNodeWidgetRef], str],
        default_criticality: Callable[[str], str],
        is_manual_workflow_model: Callable[[Any], bool],
        manual_workflow_model_key: Callable[[Any], tuple[str, str] | None],
        cleanup_orphaned_workflow_state: Callable[..., Any],
    ) -> None:
        self.pyproject = pyproject
        self.model_repository = model_repository
        self.normalize_package_id = normalize_package_id
        self.category_for_node_ref = category_for_node_ref
        self.default_criticality = default_criticality
        self.is_manual_workflow_model = is_manual_workflow_model
        self.manual_workflow_model_key = manual_workflow_model_key
        self.cleanup_orphaned_workflow_state = cleanup_orphaned_workflow_state

    def write_single_node_resolution(self, workflow_name: str, node_package_id: str) -> None:
        """Add one resolved node package to a workflow manifest entry."""
        normalized_id = self.normalize_package_id(node_package_id)

        workflows_config = self.pyproject.workflows.get_all_with_resolutions()
        workflow_config = workflows_config.get(workflow_name, {})
        existing_nodes = set(workflow_config.get("nodes", []))
        existing_nodes.add(normalized_id)

        self.pyproject.workflows.set_node_packs(workflow_name, existing_nodes)
        logger.debug(f"Added {normalized_id} to workflow '{workflow_name}' nodes")

    def write_model_resolution_grouped(
        self,
        workflow_name: str,
        resolved: ResolvedModel,
        all_refs: list[WorkflowNodeWidgetRef],
    ) -> bool:
        """Write one model resolution for one or more workflow node references.

        Returns True when the caller should invalidate the workflow resolution
        cache because a download intent was added.
        """
        primary_ref = resolved.reference
        model = resolved.resolved_model

        category = self.category_for_node_ref(primary_ref)
        criticality = "optional" if resolved.is_optional else self.default_criticality(category)

        if resolved.match_type in ("download_intent", "property_download_intent"):
            manifest_model = ManifestWorkflowModel(
                filename=primary_ref.widget_value,
                category=category,
                criticality=criticality,
                status="unresolved",
                nodes=all_refs,
                sources=[resolved.model_source] if resolved.model_source else [],
                relative_path=resolved.target_path.as_posix() if resolved.target_path else None,
            )
            self.pyproject.workflows.add_workflow_model(workflow_name, manifest_model)
            return True

        if model is None:
            manifest_model = ManifestWorkflowModel(
                filename=primary_ref.widget_value,
                category=category,
                criticality=criticality,
                status="unresolved",
                nodes=all_refs,
                sources=[],
            )
        else:
            sources = []
            if model.hash:
                sources_from_repo = self.model_repository.get_sources(model.hash)
                sources = [s["url"] for s in sources_from_repo]

            manifest_model = ManifestWorkflowModel(
                hash=model.hash,
                filename=model.filename,
                category=category,
                criticality=criticality,
                status="resolved",
                nodes=all_refs,
                sources=sources,
            )

            global_model = ManifestModel(
                hash=model.hash,
                filename=model.filename,
                size=model.file_size,
                relative_path=model.relative_path,
                category=category,
                sources=sources,
            )
            self.pyproject.models.add_model(global_model)

        self.pyproject.workflows.add_workflow_model(workflow_name, manifest_model)

        if len(all_refs) > 1:
            node_ids = ", ".join(f"#{ref.node_id}" for ref in all_refs)
            logger.debug(f"Wrote grouped model resolution for nodes: {node_ids}")
        return False

    def apply_resolution(self, resolution: ResolutionResult, *, config: dict) -> None:
        """Reconcile one full workflow resolution result into the manifest."""
        workflow_name = resolution.workflow_name

        target_node_pack_ids = set()
        target_node_types = set()

        for pkg in resolution.nodes_resolved:
            if pkg.is_optional:
                target_node_types.add(pkg.node_type)
            elif pkg.package_id is not None:
                normalized_id = self.normalize_package_id(pkg.package_id)
                target_node_pack_ids.add(normalized_id)
                target_node_types.add(pkg.node_type)

        for node in resolution.nodes_unresolved:
            target_node_types.add(node.type)
        for node in resolution.nodes_version_gated:
            target_node_types.add(node.type)
        for pkg in resolution.nodes_uninstallable:
            target_node_types.add(pkg.node_type)
        for packages in resolution.nodes_ambiguous:
            if packages:
                target_node_types.add(packages[0].node_type)

        if target_node_pack_ids:
            self.pyproject.workflows.set_node_packs(workflow_name, target_node_pack_ids, config=config)
        else:
            self.pyproject.workflows.set_node_packs(workflow_name, None, config=config)

        existing_custom_map = self.pyproject.workflows.get_custom_node_map(workflow_name, config=config)
        for node_type in list(existing_custom_map.keys()):
            if node_type not in target_node_types:
                self.pyproject.workflows.remove_custom_node_mapping(workflow_name, node_type, config=config)

        existing_workflow_models = self.pyproject.workflows.get_workflow_models(workflow_name, config=config)
        manual_workflow_models = [
            model for model in existing_workflow_models
            if self.is_manual_workflow_model(model)
        ]

        manifest_models = self._build_manifest_models(
            resolution,
            existing_workflow_models=existing_workflow_models,
            config=config,
        )

        existing_keys = {
            self.manual_workflow_model_key(model)
            for model in manifest_models
            if self.manual_workflow_model_key(model) is not None
        }
        for manual_model in manual_workflow_models:
            manual_key = self.manual_workflow_model_key(manual_model)
            if manual_key is None or manual_key in existing_keys:
                continue
            manifest_models.append(manual_model)
            existing_keys.add(manual_key)

        self.pyproject.workflows.set_workflow_models(workflow_name, manifest_models, config=config)

        self.cleanup_orphaned_workflow_state(config=config)
        self.pyproject.models.cleanup_orphans(config=config)

    def _build_manifest_models(
        self,
        resolution: ResolutionResult,
        *,
        existing_workflow_models: list[Any],
        config: dict,
    ) -> list[ManifestWorkflowModel]:
        manifest_models: list[ManifestWorkflowModel] = []

        hash_to_refs: dict[str, list[WorkflowNodeWidgetRef]] = {}
        for resolved in resolution.models_resolved:
            if resolved.resolved_model:
                model_hash = resolved.resolved_model.hash
                hash_to_refs.setdefault(model_hash, []).append(resolved.reference)
            elif resolved.match_type in ("download_intent", "property_download_intent"):
                manifest_models.append(self._download_intent_model(resolved))
            elif resolved.is_optional:
                manifest_models.append(self._optional_unresolved_model(resolved.reference))

        for model_hash, refs in hash_to_refs.items():
            model = next(
                (
                    r.resolved_model
                    for r in resolution.models_resolved
                    if r.resolved_model and r.resolved_model.hash == model_hash
                ),
                None,
            )
            if not model:
                continue

            criticality = self.default_criticality(model.category)
            sources_from_repo = self.model_repository.get_sources(model.hash)
            sources = [s["url"] for s in sources_from_repo]

            manifest_models.append(
                ManifestWorkflowModel(
                    hash=model.hash,
                    filename=model.filename,
                    category=model.category,
                    criticality=criticality,
                    status="resolved",
                    nodes=refs,
                    sources=[],
                )
            )

            self.pyproject.models.add_model(
                ManifestModel(
                    hash=model.hash,
                    filename=model.filename,
                    size=model.file_size,
                    relative_path=model.relative_path,
                    category=model.category,
                    sources=sources,
                ),
                config=config,
            )

        existing_by_filename = {m.filename: m for m in existing_workflow_models}

        for ref in resolution.models_unresolved:
            category = self.category_for_node_ref(ref)
            criticality = self.default_criticality(category)
            existing = existing_by_filename.get(ref.widget_value)
            sources = []
            relative_path = None
            if existing and existing.status == "unresolved" and existing.sources:
                sources = existing.sources
                relative_path = existing.relative_path
                logger.debug(
                    f"Preserving download intent for '{ref.widget_value}': "
                    f"sources={sources}, path={relative_path}"
                )

            manifest_models.append(
                ManifestWorkflowModel(
                    filename=ref.widget_value,
                    category=category,
                    criticality=criticality,
                    status="unresolved",
                    nodes=[ref],
                    sources=sources,
                    relative_path=relative_path,
                )
            )

        return manifest_models

    def _download_intent_model(self, resolved: ResolvedModel) -> ManifestWorkflowModel:
        category = self.category_for_node_ref(resolved.reference)
        return ManifestWorkflowModel(
            filename=resolved.reference.widget_value,
            category=category,
            criticality="flexible",
            status="unresolved",
            nodes=[resolved.reference],
            sources=[resolved.model_source] if resolved.model_source else [],
            relative_path=resolved.target_path.as_posix() if resolved.target_path else None,
        )

    def _optional_unresolved_model(self, ref: WorkflowNodeWidgetRef) -> ManifestWorkflowModel:
        category = self.category_for_node_ref(ref)
        return ManifestWorkflowModel(
            filename=ref.widget_value,
            category=category,
            criticality="optional",
            status="unresolved",
            nodes=[ref],
            sources=[],
        )
