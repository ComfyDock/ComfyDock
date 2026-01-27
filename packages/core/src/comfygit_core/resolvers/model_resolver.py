"""ModelResolver - Resolve model requirements for environment import/export."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..configs.model_config import ModelConfig
from ..logging.logging_config import get_logger
from ..models.workflow import (
    ModelResolutionContext,
    ResolvedModel,
    WorkflowNodeWidgetRef,
)

if TYPE_CHECKING:
    from ..models.shared import ModelWithLocation
    from ..repositories.model_repository import ModelRepository

logger = get_logger(__name__)


class ModelResolver:
    """Resolve model requirements for environments using multiple strategies."""

    def __init__(
        self,
        model_repository: ModelRepository,
        model_config: ModelConfig | None = None,
        cec_path: Path | None = None,
        download_manager=None,
    ):
        """Initialize ModelResolver.

        Args:
            model_repository: ModelRepository for model lookups
            model_config: Optional pre-loaded ModelConfig instance
            cec_path: Optional path to comfy_execution_config.yaml for dynamic loading
            download_manager: Optional ModelDownloadManager for downloading
        """
        self.model_repository = model_repository
        self.model_config = model_config or ModelConfig.load(cec_path=cec_path)
        self.download_manager = download_manager

    def resolve_model(
        self, ref: WorkflowNodeWidgetRef, model_context: ModelResolutionContext
    ) -> list[ResolvedModel] | None:
        """Try multiple resolution strategies"""
        workflow_name = model_context.workflow_name
        widget_value = ref.widget_value

        # Strategy 0: Check existing pyproject model data first
        context_resolution_result = self._try_context_resolution(widget_ref=ref, context=model_context)
        if context_resolution_result:
            logger.debug(
                f"Resolved {ref} to {context_resolution_result.resolved_model} from pyproject.toml"
            )
            return [context_resolution_result]

        # Strategy 1: Exact path match
        all_models = self.model_repository.get_all_models()
        candidates = self._try_exact_match(widget_value, all_models)
        if len(candidates) == 1:
            logger.debug(f"Resolved {ref} to {candidates[0]} as exact match")
            return [
                ResolvedModel(
                    workflow=workflow_name,
                    reference=ref,
                    match_type="exact",
                    resolved_model=candidates[0],
                    match_confidence=1.0,
                )
            ]

        # Strategy 2: Reconstruct paths for native loaders
        if self.model_config.is_model_loader_node(ref.node_type):
            paths = self.model_config.reconstruct_model_path(
                ref.node_type, widget_value
            )
            for path in paths:
                candidates = self._try_exact_match(path, all_models)
                if len(candidates) == 1:
                    logger.debug(
                        f"Resolved {ref} to {candidates[0]} as reconstructed match"
                    )
                    return [
                        ResolvedModel(
                            workflow=workflow_name,
                            reference=ref,
                            match_type="reconstructed",
                            resolved_model=candidates[0],
                            match_confidence=0.9,
                        )
                    ]

        # Strategy 3: Case-insensitive match
        candidates = self._try_case_insensitive_match(widget_value, all_models)
        if len(candidates) == 1:
            logger.debug(f"Resolved {ref} to {candidates[0]} as case-insensitive match")
            return [
                ResolvedModel(
                    workflow=workflow_name,
                    reference=ref,
                    match_type="case_insensitive",
                    resolved_model=candidates[0],
                    match_confidence=0.8,
                )
            ]
        elif len(candidates) > 1:
            # Multiple matches - need disambiguation
            logger.debug(
                f"Resolved {ref} to {candidates} as case-insensitive match, ambiguous"
            )
            return [
                ResolvedModel(
                    workflow=workflow_name,
                    reference=ref,
                    match_type="case_insensitive",
                    resolved_model=model,
                    match_confidence=0.0,
                )
                for model in candidates
            ]

        # Strategy 4: Filename-only match
        filename = Path(widget_value).name
        candidates = self.model_repository.find_by_filename(filename)
        if len(candidates) == 1:
            logger.debug(f"Resolved {ref} to {candidates[0]} as filename-only match")
            return [
                ResolvedModel(
                    workflow=workflow_name,
                    reference=ref,
                    match_type="filename",
                    resolved_model=candidates[0],
                    match_confidence=0.7,
                )
            ]
        elif len(candidates) > 1:
            # Multiple matches - need disambiguation
            logger.debug(
                f"Resolved {ref} to {candidates} as filename-only match, ambiguous"
            )
            return [
                ResolvedModel(
                    workflow=workflow_name,
                    reference=ref,
                    match_type="filename",
                    resolved_model=model,
                    match_confidence=0.0,
                )
                for model in candidates
            ]

        # Strategy 5: Auto-create download intent from properties.models metadata
        if ref.property_url:
            target_directory = ref.property_directory or self._infer_directory_for_node(ref.node_type)
            target_path = Path(target_directory) / Path(ref.widget_value).name
            logger.debug(
                f"Creating property-based download intent for {ref.widget_value} "
                f"from URL: {ref.property_url} -> {target_path}"
            )
            return [
                ResolvedModel(
                    workflow=workflow_name,
                    reference=ref,
                    resolved_model=None,
                    model_source=ref.property_url,
                    target_path=target_path,
                    match_type="property_download_intent",
                    match_confidence=1.0,
                )
            ]

        # No matches found
        logger.debug(f"No matches found in pyproject or model index for {ref}")
        return None

    def _infer_directory_for_node(self, node_type: str) -> str:
        """Infer target model directory from node type.

        Uses model_config mappings to determine appropriate directory.
        Falls back to 'models' if node type is unknown.
        """
        directories = self.model_config.get_directories_for_node(node_type)
        if directories:
            return directories[0]  # Use first directory as default
        return "models"

    def _try_exact_match(self, path: str, all_models: list[ModelWithLocation] | None =None) -> list[ModelWithLocation]:
        """Try exact path match"""
        if all_models is None:
            all_models = self.model_repository.get_all_models()
        return [m for m in all_models if m.relative_path == path]

    def _try_case_insensitive_match(self, path: str, all_models: list[ModelWithLocation] | None =None) -> list[ModelWithLocation]:
        """Try case-insensitive path match"""
        if all_models is None:
            all_models = self.model_repository.get_all_models()
        path_lower = path.lower()
        return [m for m in all_models if m.relative_path.lower() == path_lower]

    def _try_context_resolution(self, context: ModelResolutionContext, widget_ref: WorkflowNodeWidgetRef) -> ResolvedModel | None:
        """Check if this ref was previously resolved using context lookup.

        Handles:
        - Download intents (status=unresolved with sources) - returns download_intent
        - Optional unresolved (criticality=optional) - returns resolved with is_optional=True
        - Resolved models with hash - looks up in repository, returns None if deleted
        """
        workflow_name = context.workflow_name

        # Check if ref exists in previous resolutions (now contains full ManifestWorkflowModel)
        manifest_model = context.previous_resolutions.get(widget_ref)

        if not manifest_model:
            return None

        # NEW: Check if download intent (has URL but no hash yet)
        if manifest_model.status == "unresolved" and manifest_model.sources:
            # Download intent found - don't re-prompt user
            from pathlib import Path
            return ResolvedModel(
                workflow=workflow_name,
                reference=widget_ref,
                match_type="download_intent",
                resolved_model=None,
                model_source=manifest_model.sources[0],  # URL from previous session
                target_path=Path(manifest_model.relative_path) if manifest_model.relative_path else None,
                is_optional=False,
                match_confidence=1.0,
            )

        # Handle optional unresolved models (user explicitly marked as optional)
        if manifest_model.status == "unresolved" and not manifest_model.sources:
            # Only treat as optional if user explicitly marked it (criticality="optional")
            # Otherwise it's just unresolved (from interrupted resolution) - return None
            if manifest_model.criticality == "optional":
                return ResolvedModel(
                    workflow=workflow_name,
                    reference=widget_ref,
                    match_type="workflow_context",
                    resolved_model=None,
                    is_optional=True,
                    match_confidence=1.0,
                )
            # Not explicitly optional - this is truly unresolved, let it fall through
            return None

        # Handle resolved models - look up in repository by hash
        if manifest_model.hash:
            resolved_model = self.model_repository.get_model(manifest_model.hash)

            if not resolved_model:
                # Model was previously resolved but no longer exists in repository
                # Return None so it goes to models_unresolved
                # cleanup_orphans() will remove stale entry from global table during apply_resolution()
                logger.warning(
                    f"Model {manifest_model.hash[:8]}... ({manifest_model.filename}) "
                    f"marked as resolved but not found in model repository. "
                    f"Will be treated as unresolved."
                )
                return None

            return ResolvedModel(
                workflow=workflow_name,
                reference=widget_ref,
                match_type="workflow_context",
                resolved_model=resolved_model,
                match_confidence=1.0,
            )

        return None
