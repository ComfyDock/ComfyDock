"""Workflow model path and category policy."""

from __future__ import annotations

from typing import Any, Protocol, cast

from ..logging.logging_config import get_logger
from ..models.shared import ModelWithLocation
from ..models.workflow import ResolutionResult, ResolvedModel, WorkflowNodeWidgetRef
from ..repositories.workflow_repository import WorkflowRepository
from ..utils.model_categories import get_model_category
from .workflow_file_store import WorkflowFileStore

logger = get_logger(__name__)

CATEGORY_CRITICALITY_DEFAULTS = {
    "checkpoints": "flexible",
    "vae": "flexible",
    "text_encoders": "flexible",
    "loras": "flexible",
    "controlnet": "required",
    "clip_vision": "required",
    "style_models": "flexible",
    "embeddings": "flexible",
    "upscale_models": "flexible",
}


class ModelConfigLike(Protocol):
    """Model loader metadata used by workflow model path policy."""

    def get_directories_for_node(self, node_type: str) -> list[str]:
        """Return model directories scanned by a ComfyUI node type."""
        ...

    def is_model_loader_node(self, node_type: str) -> bool:
        """Return whether the node type is a known model loader."""
        ...

    def reconstruct_model_path(self, node_type: str, widget_value: str) -> list[str]:
        """Return possible model-relative paths for a widget value."""
        ...


class ModelRepositoryLike(Protocol):
    """Model index lookups used by workflow model path policy."""

    def get_all_models(self) -> list[ModelWithLocation]:
        """Return all indexed model locations."""
        ...

    def get_locations(self, model_hash: str) -> list[dict[str, Any]]:
        """Return all indexed locations for a model hash."""
        ...


class WorkflowCacheInvalidator(Protocol):
    """Cache invalidation used after mutating workflow JSON."""

    def invalidate(self, *, env_name: str, workflow_name: str) -> None:
        """Invalidate cached workflow analysis for one workflow."""
        ...


class WorkflowModelPathPolicy:
    """Owns ComfyUI model-loader path policy for workflow resolution.

    This service is intentionally pyproject-agnostic. It converts resolved model
    locations into the widget values expected by builtin ComfyUI loader nodes and
    annotates resolution results with path/category issues.
    """

    def __init__(
        self,
        *,
        model_repository: ModelRepositoryLike,
        model_config: ModelConfigLike,
        workflow_file_store: WorkflowFileStore,
        workflow_cache: WorkflowCacheInvalidator | None,
        environment_name: str,
    ) -> None:
        self.model_repository = model_repository
        self.model_config = model_config
        self.workflow_file_store = workflow_file_store
        self.workflow_cache = workflow_cache
        self.environment_name = environment_name

    def annotate_resolution(self, resolution: ResolutionResult) -> None:
        """Annotate resolved models with path sync and category mismatch flags."""
        for resolved_model in resolution.models_resolved:
            if not resolved_model.resolved_model:
                continue
            resolved_model.needs_path_sync = self.path_needs_sync(resolved_model)
            has_mismatch, expected, actual = self.category_mismatch(resolved_model)
            resolved_model.has_category_mismatch = has_mismatch
            resolved_model.expected_categories = expected
            resolved_model.actual_category = actual

    def update_workflow_model_paths(self, resolution: ResolutionResult) -> int:
        """Update workflow JSON model widget values for builtin model loaders."""
        workflow_name = resolution.workflow_name
        workflow_path = self.workflow_file_store.get_workflow_path(workflow_name)
        workflow = WorkflowRepository.load(workflow_path)

        updated_count = 0
        skipped_count = 0

        for resolved in resolution.models_resolved:
            ref = resolved.reference
            model = resolved.resolved_model
            if model is None:
                continue

            if not self.model_config.is_model_loader_node(ref.node_type):
                logger.debug(
                    "Skipping path update for custom node '%s' (node_id=%s, widget=%s). "
                    "Custom nodes manage their own model paths.",
                    ref.node_type,
                    ref.node_id,
                    ref.widget_index,
                )
                skipped_count += 1
                continue

            if ref.node_id not in workflow.nodes:
                continue
            node = workflow.nodes[ref.node_id]
            if ref.widget_index >= len(node.widgets_values):
                continue

            old_path = node.widgets_values[ref.widget_index]
            display_path = self.strip_base_directory_for_node(
                ref.node_type,
                model.relative_path,
            )
            if old_path == display_path:
                continue
            node.widgets_values[ref.widget_index] = display_path
            logger.debug(
                "Updated node %s widget %s: %s -> %s",
                ref.node_id,
                ref.widget_index,
                old_path,
                display_path,
            )
            updated_count += 1

        if updated_count > 0:
            WorkflowRepository.save(workflow, workflow_path)
            self._invalidate(workflow_name)
            logger.info(
                "Updated workflow JSON: %s (%s builtin nodes updated, %s custom nodes preserved)",
                workflow_path,
                updated_count,
                skipped_count,
            )
        else:
            logger.debug("No path updates needed for workflow '%s'", workflow_name)

        return updated_count

    def default_criticality(self, category: str) -> str:
        """Return the default criticality for a model category."""
        return CATEGORY_CRITICALITY_DEFAULTS.get(category, "required")

    def category_for_node_ref(self, node_ref: WorkflowNodeWidgetRef) -> str:
        """Return the model category associated with a workflow model reference."""
        node_type = node_ref.node_type
        directories = self.model_config.get_directories_for_node(node_type)
        if directories:
            logger.debug(
                "Found directory mapping for node type '%s': %s",
                node_type,
                directories,
            )
            return directories[0]

        category = get_model_category(
            node_ref.widget_value,
            model_config=cast(Any, self.model_config),
        )
        logger.debug(
            "Found directory mapping for widget value '%s': %s",
            node_ref.widget_value,
            category,
        )
        return category

    def path_needs_sync(self, resolved: ResolvedModel) -> bool:
        """Return whether a workflow widget path differs from resolved model path."""
        ref = resolved.reference
        model = resolved.resolved_model

        if not self.model_config.is_model_loader_node(ref.node_type):
            return False
        if not model:
            return False

        expected_path = self.strip_base_directory_for_node(
            ref.node_type,
            model.relative_path,
        )
        current_path = ref.widget_value.replace("\\", "/")

        if current_path != expected_path and self._current_path_has_same_hash(
            ref,
            current_path,
            model.hash,
        ):
            return False

        return current_path != expected_path

    def category_mismatch(
        self,
        resolved: ResolvedModel,
    ) -> tuple[bool, list[str], str | None]:
        """Return whether a resolved model is in a directory unusable by its loader."""
        ref = resolved.reference
        model = resolved.resolved_model

        if not model:
            return (False, [], None)
        if not self.model_config.is_model_loader_node(ref.node_type):
            return (False, [], None)

        expected_dirs = self.model_config.get_directories_for_node(ref.node_type)
        if not expected_dirs:
            return (False, [], None)

        actual_category = self._category_from_relative_path(model.relative_path)
        if actual_category in expected_dirs:
            return (False, expected_dirs, actual_category)

        for location in self.model_repository.get_locations(model.hash):
            location_path = location.get("relative_path")
            if not isinstance(location_path, str):
                continue
            if self._category_from_relative_path(location_path) in expected_dirs:
                return (False, expected_dirs, actual_category)

        return (True, expected_dirs, actual_category)

    def strip_base_directory_for_node(self, node_type: str, relative_path: str) -> str:
        """Strip builtin loader base directory prefixes from model-relative paths."""
        relative_path = relative_path.replace("\\", "/")
        base_dirs = self.model_config.get_directories_for_node(node_type)

        if not base_dirs:
            logger.warning(
                "strip_base_directory_for_node called for unknown/custom node type: %s. "
                "Custom nodes should skip path updates entirely. Returning path unchanged.",
                node_type,
            )
            return relative_path

        for base_dir in base_dirs:
            prefix = base_dir + "/"
            if relative_path.startswith(prefix):
                return relative_path[len(prefix):]

        return relative_path

    @staticmethod
    def _category_from_relative_path(relative_path: str) -> str | None:
        path_parts = relative_path.replace("\\", "/").split("/")
        return path_parts[0] if path_parts else None

    @staticmethod
    def _normalize_model_path(path: str) -> str:
        return path.replace("\\", "/")

    def _current_path_has_same_hash(
        self,
        ref: WorkflowNodeWidgetRef,
        current_path: str,
        expected_hash: str,
    ) -> bool:
        all_models = self.model_repository.get_all_models()
        current_matches = self._exact_path_matches(current_path, all_models)

        if not current_matches:
            for path in self.model_config.reconstruct_model_path(ref.node_type, current_path):
                current_matches = self._exact_path_matches(path, all_models)
                if current_matches:
                    break

        return bool(current_matches and current_matches[0].hash == expected_hash)

    def _exact_path_matches(
        self,
        path: str,
        all_models: list[ModelWithLocation],
    ) -> list[ModelWithLocation]:
        normalized_path = self._normalize_model_path(path)
        return [
            model
            for model in all_models
            if self._normalize_model_path(model.relative_path) == normalized_path
        ]

    def _invalidate(self, workflow_name: str) -> None:
        if self.workflow_cache is None:
            return
        self.workflow_cache.invalidate(
            env_name=self.environment_name,
            workflow_name=workflow_name,
        )
