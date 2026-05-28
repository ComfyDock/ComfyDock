"""Environment model manager for orchestrating model operations.

Coordinates model-related operations across pyproject, repository, and downloader.
Handles source management, missing model detection, and import preparation.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ..logging.logging_config import get_logger
from ..models.shared import ModelSourceResult, ModelSourceStatus

if TYPE_CHECKING:
    from ..repositories.model_repository import ModelRepository
    from ..services.model_downloader import ModelDownloader
    from .pyproject_manager import PyprojectManager


logger = get_logger(__name__)


class EnvironmentModelManager:
    """Orchestrates model operations across multiple managers and services.

    Responsibilities:
    - Add/query model download sources (pyproject + repository)
    - Detect missing models across workflows
    - Prepare import strategies (convert resolved models to download intents)
    - Enrich SQLite index with pyproject sources
    """

    def __init__(
        self,
        pyproject: PyprojectManager,
        model_repository: ModelRepository,
        model_downloader: ModelDownloader,
    ):
        self.pyproject = pyproject
        self.model_repository = model_repository
        self.model_downloader = model_downloader

    @staticmethod
    def _normalize_model_relative_path(relative_path: str) -> str:
        normalized = relative_path.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Model path must be relative to the models directory: {relative_path}")
        return path.as_posix()

    def _get_available_workflow_model(self, workflow_model):
        """Return the indexed model only if the workflow's required location is present."""
        model_hash = getattr(workflow_model, "hash", None)
        if not model_hash:
            return None

        relative_path = getattr(workflow_model, "relative_path", None)
        if relative_path:
            try:
                indexed = self.model_repository.find_by_exact_path(
                    self._normalize_model_relative_path(relative_path)
                )
            except ValueError:
                return None
            if indexed and indexed.hash == model_hash:
                return indexed
            return None

        return self.model_repository.get_model(model_hash)

    def add_model_source(self, identifier: str, url: str) -> ModelSourceResult:
        """Add a download source URL to a model.

        Updates both pyproject.toml and the workspace model index.

        Args:
            identifier: Model hash or filename
            url: Download URL for the model

        Returns:
            ModelSourceResult with success status and model details
        """
        # Find model by hash or filename
        all_models = self.pyproject.models.get_all()

        model = None

        # Try exact hash match first (unambiguous)
        hash_matches = [m for m in all_models if m.hash == identifier]
        if hash_matches:
            model = hash_matches[0]
        else:
            # Try filename match (potentially ambiguous)
            filename_matches = [m for m in all_models if m.filename == identifier]

            if len(filename_matches) == 0:
                return ModelSourceResult(
                    success=False,
                    error="model_not_found",
                    identifier=identifier
                )
            elif len(filename_matches) > 1:
                return ModelSourceResult(
                    success=False,
                    error="ambiguous_filename",
                    identifier=identifier,
                    matches=filename_matches
                )
            else:
                model = filename_matches[0]

        # Check if URL already exists
        if url in model.sources:
            return ModelSourceResult(
                success=False,
                error="url_exists",
                model=model,
                model_hash=model.hash
            )

        # Detect source type
        source_type = self.model_downloader.detect_url_type(url)

        # Update pyproject.toml through the manifest domain API.
        self.pyproject.manifest.add_model_source(model.hash, url)

        # Update model repository (SQLite index) - only if model exists locally
        if self.model_repository.has_model(model.hash):
            self.model_repository.add_source(
                model_hash=model.hash,
                source_type=source_type,
                source_url=url
            )

        logger.info(f"Added source to model {model.filename}: {url}")

        return ModelSourceResult(
            success=True,
            model=model,
            model_hash=model.hash,
            source_type=source_type,
            url=url
        )

    def remove_model_source(self, identifier: str, url: str) -> ModelSourceResult:
        """Remove a download source URL from a model.

        Updates both pyproject.toml and the workspace model index.

        Args:
            identifier: Model hash or filename
            url: Download URL to remove

        Returns:
            ModelSourceResult with success status and model details
        """
        # Find model by hash or filename
        all_models = self.pyproject.models.get_all()

        model = None

        # Try exact hash match first (unambiguous)
        hash_matches = [m for m in all_models if m.hash == identifier]
        if hash_matches:
            model = hash_matches[0]
        else:
            # Try filename match (potentially ambiguous)
            filename_matches = [m for m in all_models if m.filename == identifier]

            if len(filename_matches) == 0:
                return ModelSourceResult(
                    success=False,
                    error="model_not_found",
                    identifier=identifier
                )
            elif len(filename_matches) > 1:
                return ModelSourceResult(
                    success=False,
                    error="ambiguous_filename",
                    identifier=identifier,
                    matches=filename_matches
                )
            else:
                model = filename_matches[0]

        # Check if URL exists in model sources
        if url not in model.sources:
            return ModelSourceResult(
                success=False,
                error="url_not_found",
                model=model,
                model_hash=model.hash
            )

        # Update pyproject.toml through the manifest domain API.
        self.pyproject.manifest.remove_model_source(model.hash, url)

        # Update model repository (SQLite index) - only if model exists locally
        if self.model_repository.has_model(model.hash):
            self.model_repository.remove_source(
                model_hash=model.hash,
                source_url=url
            )

        logger.info(f"Removed source from model {model.filename}: {url}")

        return ModelSourceResult(
            success=True,
            model=model,
            model_hash=model.hash,
            url=url
        )

    def get_models_without_sources(self) -> list[ModelSourceStatus]:
        """Get all models in pyproject that don't have download sources.

        Returns:
            List of ModelSourceStatus objects with model and local availability
        """
        all_models = self.pyproject.models.get_all()

        results = []
        for model in all_models:
            if not model.sources:
                # Check if model exists in local index
                local_model = self.model_repository.get_model(model.hash)

                results.append(ModelSourceStatus(
                    model=model,
                    available_locally=local_model is not None
                ))

        return results

    def detect_missing_models(self) -> list:
        """Detect models in pyproject that don't exist in local index.

        Checks both resolved workflow models (with hash) and models in the global table
        that aren't present in the local repository with valid file locations.

        Returns:
            List of MissingModelInfo for models that need downloading
        """
        from ..models.environment import MissingModelInfo

        missing_by_hash: dict[str, MissingModelInfo] = {}

        # Get all workflows
        all_workflows = self.pyproject.workflows.get_all_with_resolutions()

        # First pass: Check all workflow models for missing resolved models
        for workflow_name in all_workflows.keys():
            workflow_models = self.pyproject.workflows.get_workflow_models(workflow_name)

            for wf_model in workflow_models:
                model_hash = wf_model.hash

                # If model has a hash, check if it exists WITH a valid location
                if model_hash and not self._get_available_workflow_model(wf_model):
                    if model_hash not in missing_by_hash:
                        global_model = self.pyproject.models.get_by_hash(model_hash)
                        if global_model:
                            missing_by_hash[model_hash] = MissingModelInfo(
                                model=global_model,
                                workflow_names=[workflow_name],
                                criticality=wf_model.criticality,
                                can_download=bool(global_model.sources)
                            )
                    else:
                        # Already tracking, update
                        missing_info = missing_by_hash[model_hash]
                        if workflow_name not in missing_info.workflow_names:
                            missing_info.workflow_names.append(workflow_name)
                        # Upgrade criticality
                        if wf_model.criticality == "required":
                            missing_info.criticality = "required"
                        elif wf_model.criticality == "flexible" and missing_info.criticality == "optional":
                            missing_info.criticality = "flexible"

        # Second pass: Check global models table for any models not in repository
        global_models = self.pyproject.models.get_all()
        for global_model in global_models:
            if global_model.hash not in missing_by_hash:
                if not self.model_repository.get_model(global_model.hash):
                    # Find which workflows use this model
                    workflows_using_model = []
                    criticality = "flexible"

                    for workflow_name in all_workflows.keys():
                        workflow_models = self.pyproject.workflows.get_workflow_models(workflow_name)
                        for wf_model in workflow_models:
                            if wf_model.hash == global_model.hash:
                                workflows_using_model.append(workflow_name)
                                if wf_model.criticality == "required":
                                    criticality = "required"
                                elif wf_model.criticality == "flexible" and criticality == "optional":
                                    criticality = "flexible"

                    # Only add if used by at least one workflow
                    if workflows_using_model:
                        missing_by_hash[global_model.hash] = MissingModelInfo(
                            model=global_model,
                            workflow_names=workflows_using_model,
                            criticality=criticality,
                            can_download=bool(global_model.sources)
                        )

        return list(missing_by_hash.values())

    def prepare_import_with_model_strategy(self, strategy: str = "all") -> list[str]:
        """Prepare import by converting missing models to download intents.

        This detects which models are missing locally and temporarily converts
        them back to download intents in pyproject.toml. Subsequent resolve_workflow()
        calls will download them.

        Args:
            strategy: Model download strategy
                - "all": Download all models with sources
                - "required": Download only required models
                - "skip": Skip all downloads (leave as optional unresolved)

        Returns:
            List of workflow names that had download intents prepared
        """
        logger.info(f"Preparing import with model strategy: {strategy}")

        workflows_with_intents = []
        all_workflows = self.pyproject.workflows.get_all_with_resolutions()

        for workflow_name in all_workflows.keys():
            models = self.pyproject.workflows.get_workflow_models(workflow_name)
            models_modified = False
            has_download_intents = False
            has_required_download_intents = False

            for idx, model in enumerate(models):
                # Existing download intent (already unresolved with sources)
                if model.status == "unresolved":
                    if model.sources:
                        has_download_intents = True
                        if model.criticality == "required":
                            has_required_download_intents = True
                    continue

                # Check if model exists locally
                if model.hash:
                    existing = self._get_available_workflow_model(model)
                    if existing:
                        # Enrich SQLite with sources from pyproject
                        global_model = self.pyproject.models.get_by_hash(model.hash)
                        if global_model and global_model.sources:
                            existing_sources_list = self.model_repository.get_sources(model.hash)
                            existing_source_urls = {s["url"] for s in existing_sources_list}

                            for source_url in global_model.sources:
                                if source_url not in existing_source_urls:
                                    source_type = self.model_downloader.detect_url_type(source_url)
                                    self.model_repository.add_source(
                                        model_hash=model.hash,
                                        source_type=source_type,
                                        source_url=source_url
                                    )
                                    logger.info(f"Enriched model {global_model.filename} with source: {source_url}")

                        continue

                # Model missing - prepare download intent with sources
                if model.hash:
                    global_model = self.pyproject.models.get_by_hash(model.hash)
                    if global_model and global_model.sources:
                        models[idx].status = "unresolved"
                        models[idx].sources = global_model.sources
                        models[idx].relative_path = global_model.relative_path
                        models[idx].hash = None
                        models_modified = True
                        has_download_intents = True
                        if models[idx].criticality == "required":
                            has_required_download_intents = True
                        logger.debug(f"Prepared download intent for {model.filename} in {workflow_name}")

            # Save modified models
            if models_modified:
                self.pyproject.workflows.set_workflow_models(workflow_name, models)

            # Add to workflows_with_intents based on strategy.
            # Include workflows that already had unresolved download intents
            # before this call, not just ones modified in this pass.
            if strategy == "all" and has_download_intents:
                workflows_with_intents.append(workflow_name)
            elif strategy == "required" and has_required_download_intents:
                workflows_with_intents.append(workflow_name)

        logger.info(f"Prepared {len(workflows_with_intents)} workflows with download intents")
        return workflows_with_intents
