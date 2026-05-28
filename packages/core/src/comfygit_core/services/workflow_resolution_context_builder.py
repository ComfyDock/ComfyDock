"""Build workflow resolution contexts and matching cache fingerprints."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ..logging.logging_config import get_logger
from ..models.workflow import WorkflowDependencies, WorkflowNodeWidgetRef
from ..services.workflow_resolution_service import ResolutionContext
from ..utils.node_identity import resolve_installed_node_alias

if TYPE_CHECKING:
    from ..managers.pyproject_manager import PyprojectManager
    from ..repositories.comfyui_builtin_versions_repository import (
        ComfyUIBuiltinVersionsRepository,
    )
    from ..repositories.model_repository import ModelRepository

logger = get_logger(__name__)

PackageIdNormalizer = Callable[[str], str]


class WorkflowResolutionContextBuilder:
    """Builds runtime resolution context and cache fingerprint projections.

    Runtime resolution and cache invalidation use the same manifest/model inputs,
    but they intentionally project those inputs differently. Runtime needs the full
    set of installed packages, while the cache fingerprint should stay scoped to
    the workflow-specific data that can change the cached result.
    """

    def __init__(
        self,
        *,
        pyproject: PyprojectManager,
        model_repository: ModelRepository,
        cec_path: Path | None,
        builtin_versions_repository: ComfyUIBuiltinVersionsRepository | None,
        normalize_package_id: PackageIdNormalizer | None = None,
    ) -> None:
        self.pyproject = pyproject
        self.model_repository = model_repository
        self.cec_path = cec_path
        self.builtin_versions_repository = builtin_versions_repository
        self.normalize_package_id = normalize_package_id or (lambda package_id: package_id)

    def build_runtime_context(
        self,
        analysis: WorkflowDependencies,
        *,
        auto_select_ambiguous: bool = True,
    ) -> ResolutionContext:
        """Build the context consumed by `WorkflowResolutionService`."""
        workflow_name = analysis.workflow_name
        workflow_models = self.pyproject.workflows.get_workflow_models(workflow_name)
        previous_resolutions = self._previous_model_resolutions(workflow_models)
        current_custom_map = self.pyproject.workflows.get_custom_node_map(workflow_name)
        consensus_custom_map = self.consensus_custom_node_map(workflow_name)

        return ResolutionContext(
            installed_packages=self.pyproject.nodes.get_existing(),
            custom_node_mappings={**consensus_custom_map, **current_custom_map},
            previous_model_resolutions=previous_resolutions,
            global_models=self._global_models_by_hash(),
            cec_path=self.cec_path,
            builtin_versions_repository=self.builtin_versions_repository,
            workflow_name=workflow_name,
            auto_select_ambiguous=auto_select_ambiguous,
        )

    def consensus_custom_node_map(self, workflow_name: str) -> dict[str, str | bool]:
        """Return unambiguous normalized mappings learned from other workflows."""
        workflows = self.pyproject.workflows.get_all_with_resolutions()
        installed_nodes = self.pyproject.nodes.get_existing()
        candidates: dict[str, set[str | bool]] = {}

        for other_name, workflow_data in workflows.items():
            if other_name == workflow_name or not isinstance(workflow_data, Mapping):
                continue

            workflow_mapping = cast(Mapping[str, object], workflow_data)
            custom_map = workflow_mapping.get("custom_node_map", {})
            if not isinstance(custom_map, Mapping):
                continue

            for node_type, package_id in custom_map.items():
                if isinstance(package_id, bool):
                    normalized: str | bool = package_id
                elif isinstance(package_id, str):
                    normalized = self.normalize_package_id(package_id)
                    resolved_package_id = resolve_installed_node_alias(
                        normalized,
                        installed_nodes,
                    )
                    if not resolved_package_id:
                        continue
                    normalized = resolved_package_id
                else:
                    continue

                candidates.setdefault(str(node_type), set()).add(normalized)

        return {
            node_type: next(iter(package_ids))
            for node_type, package_ids in candidates.items()
            if len(package_ids) == 1
        }

    def build_cache_fingerprint_context(
        self,
        dependencies: WorkflowDependencies,
        *,
        workflow_name: str | None = None,
        resolution_state_hash: str,
        models_sync_time: str | None,
    ) -> dict[str, object]:
        """Build the workflow-specific resolution fingerprint payload.

        This preserves the existing cache precision rule: installed package
        metadata is fingerprinted only for packages declared by this workflow.
        Unrelated package changes should not invalidate this workflow's cache.
        """
        workflow_name = workflow_name or dependencies.workflow_name
        workflow_configs = self.pyproject.workflows.get_all_with_resolutions()
        workflow_config = workflow_configs.get(workflow_name, {})
        if not isinstance(workflow_config, Mapping):
            workflow_config = {}
        node_types = {n.type for n in dependencies.non_builtin_nodes}
        custom_map = self.pyproject.workflows.get_custom_node_map(workflow_name)
        installed_nodes = self.pyproject.nodes.get_existing()
        consensus_custom_mappings = self._cache_consensus_custom_mappings(
            workflow_name,
            node_types,
            workflow_configs,
            custom_map,
            installed_nodes,
        )

        return {
            "resolution_state_hash": resolution_state_hash,
            "custom_mappings": self._cache_custom_mappings(node_types, custom_map),
            "consensus_custom_mappings": consensus_custom_mappings,
            "consensus_declared_packages": self._cache_consensus_declared_packages(
                consensus_custom_mappings,
                installed_nodes,
            ),
            "declared_packages": self._cache_declared_packages(
                workflow_config,
                installed_nodes,
            ),
            "workflow_models_pyproject": self._cache_workflow_models(workflow_name),
            "model_index_subset": self._cache_model_index_subset(dependencies),
            "models_sync_time": models_sync_time,
        }

    @staticmethod
    def _previous_model_resolutions(workflow_models: list[Any]) -> dict[WorkflowNodeWidgetRef, Any]:
        previous_resolutions: dict[WorkflowNodeWidgetRef, Any] = {}
        for manifest_model in workflow_models:
            for ref in manifest_model.nodes:
                previous_resolutions[ref] = manifest_model
        return previous_resolutions

    def _global_models_by_hash(self) -> dict[str, Any]:
        global_models: dict[str, Any] = {}
        try:
            for model in self.pyproject.models.get_all():
                global_models[model.hash] = model
        except Exception as e:
            logger.warning(f"Failed to load global models table: {e}")
        return global_models

    @staticmethod
    def _cache_custom_mappings(
        node_types: set[str],
        custom_map: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            node_type: custom_map[node_type]
            for node_type in node_types
            if node_type in custom_map
        }

    def _cache_consensus_custom_mappings(
        self,
        workflow_name: str,
        node_types: set[str],
        workflow_configs: Mapping[str, object],
        current_custom_map: Mapping[str, object],
        installed_nodes: Mapping[str, Any],
    ) -> dict[str, str | bool]:
        # Match the runtime-effective consensus projection so alias changes in
        # installed packages cannot leave a stale cached resolution behind.
        consensus_candidates: dict[str, set[str | bool]] = {}
        for other_name, workflow_data in workflow_configs.items():
            if other_name == workflow_name or not isinstance(workflow_data, Mapping):
                continue

            workflow_mapping = cast(Mapping[str, object], workflow_data)
            other_custom_map = workflow_mapping.get("custom_node_map", {})
            if not isinstance(other_custom_map, Mapping):
                continue
            typed_custom_map = cast(Mapping[str, object], other_custom_map)

            for node_type in node_types:
                if node_type not in typed_custom_map:
                    continue
                package_id = typed_custom_map[node_type]
                if isinstance(package_id, bool):
                    resolved: str | bool = package_id
                elif isinstance(package_id, str):
                    normalized = self.normalize_package_id(package_id)
                    resolved_package_id = resolve_installed_node_alias(
                        normalized,
                        installed_nodes,
                    )
                    if not resolved_package_id:
                        continue
                    resolved = resolved_package_id
                else:
                    continue
                consensus_candidates.setdefault(node_type, set()).add(resolved)

        return {
            node_type: next(iter(package_ids))
            for node_type, package_ids in consensus_candidates.items()
            if node_type not in current_custom_map and len(package_ids) == 1
        }

    @staticmethod
    def _cache_consensus_declared_packages(
        consensus_custom_mappings: Mapping[str, str | bool],
        installed_nodes: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        consensus_package_ids = {
            package_id
            for package_id in consensus_custom_mappings.values()
            if isinstance(package_id, str)
        }
        return {
            package_id: {
                "name": installed_nodes[package_id].name,
                "registry_id": installed_nodes[package_id].registry_id,
                "version": installed_nodes[package_id].version,
                "repository": installed_nodes[package_id].repository,
                "source": installed_nodes[package_id].source,
            }
            for package_id in consensus_package_ids
            if package_id in installed_nodes
        }

    @staticmethod
    def _cache_declared_packages(
        workflow_config: Mapping[str, object],
        declared_packages: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        raw_packages = workflow_config.get("nodes", [])
        if not isinstance(raw_packages, list):
            raw_packages = []
        relevant_packages = {str(pkg) for pkg in raw_packages}
        return {
            pkg: {
                "version": declared_packages[pkg].version,
                "repository": declared_packages[pkg].repository,
                "source": declared_packages[pkg].source,
            }
            for pkg in relevant_packages
            if pkg in declared_packages
        }

    def _cache_workflow_models(self, workflow_name: str) -> dict[str, dict[str, Any]]:
        model_pyproject_data: dict[str, dict[str, Any]] = {}
        for manifest_model in self.pyproject.workflows.get_workflow_models(workflow_name):
            nodes = getattr(manifest_model, "nodes", None) or []
            if not nodes:
                key_source = (
                    getattr(manifest_model, "relative_path", None)
                    or getattr(manifest_model, "hash", None)
                    or getattr(manifest_model, "filename", None)
                    or "unknown"
                )
                model_pyproject_data[f"manual:{key_source}"] = {
                    "hash": manifest_model.hash,
                    "status": manifest_model.status,
                    "criticality": manifest_model.criticality,
                    "sources": manifest_model.sources,
                    "relative_path": manifest_model.relative_path,
                    "declared_by": getattr(manifest_model, "declared_by", None),
                }
                continue

            for ref in nodes:
                ref_key = f"{ref.node_id}_{ref.widget_index}"
                model_pyproject_data[ref_key] = {
                    "hash": manifest_model.hash,
                    "status": manifest_model.status,
                    "criticality": manifest_model.criticality,
                    "sources": manifest_model.sources,
                    "relative_path": manifest_model.relative_path,
                }
        return model_pyproject_data

    def _cache_model_index_subset(
        self,
        dependencies: WorkflowDependencies,
    ) -> dict[str, list[dict[str, Any]]]:
        model_index_subset: dict[str, list[dict[str, Any]]] = {}
        for model_ref in dependencies.found_models:
            normalized_value = model_ref.widget_value.replace("\\", "/")
            filename = normalized_value.rsplit("/", 1)[-1]
            models = self.model_repository.find_by_filename(filename)
            if not models:
                continue
            model_index_subset[filename] = [
                {
                    "hash": getattr(m, "hash", None),
                    "relative_path": getattr(m, "relative_path", None),
                    "category": getattr(m, "category", None),
                }
                for m in models
            ]
        return model_index_subset
