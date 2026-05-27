"""Workflow model dependency manifest updates."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from ..logging.logging_config import get_logger
from ..models.manifest import ManifestModel, ManifestWorkflowModel
from ..models.workflow import WorkflowNodeWidgetRef

if TYPE_CHECKING:
    from ..models.shared import ModelWithLocation

logger = get_logger(__name__)


class WorkflowModelManifestProtocol(Protocol):
    """Workflow model manifest operations used by dependency updates."""

    def get_workflow_models(
        self,
        workflow_name: str,
        config: dict | None = None,
    ) -> list[ManifestWorkflowModel]:
        """Return workflow model entries."""
        ...

    def set_workflow_models(
        self,
        workflow_name: str,
        models: list[ManifestWorkflowModel],
        config: dict | None = None,
    ) -> None:
        """Replace workflow model entries."""
        ...


class GlobalModelManifestProtocol(Protocol):
    """Global model manifest operations used by dependency updates."""

    def add_model(self, model: ManifestModel, config: dict | None = None) -> None:
        """Add or update a global model entry."""
        ...


class ModelRepositoryProtocol(Protocol):
    """Model repository reads needed by workflow dependency updates."""

    def get_model(self, hash: str) -> ModelWithLocation | None:
        """Return one indexed model by hash."""
        ...


class WorkflowModelDependencyService:
    """Owns model dependency updates inside workflow and global manifest tables."""

    def __init__(
        self,
        *,
        workflows: WorkflowModelManifestProtocol,
        models: GlobalModelManifestProtocol,
        model_repository: ModelRepositoryProtocol,
    ) -> None:
        self.workflows = workflows
        self.models = models
        self.model_repository = model_repository

    def update_criticality(
        self,
        workflow_name: str,
        model_identifier: str,
        new_criticality: str,
    ) -> bool:
        """Update criticality for workflow model entries matched by hash or filename."""
        if new_criticality not in ("required", "flexible", "optional"):
            raise ValueError(f"Invalid criticality: {new_criticality}")

        models = self.workflows.get_workflow_models(workflow_name)
        if not models:
            return False

        matches: list[tuple[int, ManifestWorkflowModel]] = []
        for idx, model in enumerate(models):
            if model.hash == model_identifier or model.filename == model_identifier:
                matches.append((idx, model))

        if not matches:
            return False

        for idx, _model in matches:
            models[idx].criticality = new_criticality

        self.workflows.set_workflow_models(workflow_name, models)

        if len(matches) == 1:
            _, model = matches[0]
            logger.info(
                f"Updated '{model.filename}' criticality to {new_criticality}"
            )
        else:
            logger.info(
                f"Updated {len(matches)} model(s) with identifier "
                f"'{model_identifier}' to criticality '{new_criticality}'"
            )
        return True

    def mark_download_resolved_by_reference(
        self,
        workflow_name: str,
        reference: WorkflowNodeWidgetRef,
        model_hash: str,
    ) -> None:
        """Mark a workflow download intent resolved by its workflow widget reference.

        Raises:
            ValueError: If the workflow model entry or indexed model cannot be found.
        """
        def matches(model: ManifestWorkflowModel) -> bool:
            return reference in model.nodes

        changed = self._mark_download_resolved(
            workflow_name,
            model_hash=model_hash,
            matches=matches,
            missing_model_returns_false=False,
        )
        if not changed:
            raise ValueError(
                f"Model with reference {reference} not found in workflow '{workflow_name}'"
            )

    def mark_download_resolved_by_filename(
        self,
        workflow_name: str,
        *,
        filename: str,
        model_hash: str,
    ) -> bool:
        """Mark a workflow download intent resolved by unresolved filename."""
        def matches(model: ManifestWorkflowModel) -> bool:
            return (
                model.filename == filename
                and model.status == "unresolved"
                and bool(model.sources)
            )

        return self._mark_download_resolved(
            workflow_name,
            model_hash=model_hash,
            matches=matches,
            missing_model_returns_false=True,
        )

    def _mark_download_resolved(
        self,
        workflow_name: str,
        *,
        model_hash: str,
        matches: Callable[[ManifestWorkflowModel], bool],
        missing_model_returns_false: bool,
    ) -> bool:
        workflow_models = self.workflows.get_workflow_models(workflow_name)

        for idx, workflow_model in enumerate(workflow_models):
            if not matches(workflow_model):
                continue

            indexed_model = self.model_repository.get_model(model_hash)
            if indexed_model is None:
                if missing_model_returns_false:
                    return False
                raise ValueError(
                    f"Model {model_hash} not found in repository after download. "
                    f"This indicates the model wasn't properly indexed."
                )

            self._write_resolved_model(
                workflow_name,
                workflow_models=workflow_models,
                workflow_model_index=idx,
                workflow_model=workflow_model,
                indexed_model=indexed_model,
            )
            return True

        return False

    def _write_resolved_model(
        self,
        workflow_name: str,
        *,
        workflow_models: list[ManifestWorkflowModel],
        workflow_model_index: int,
        workflow_model: ManifestWorkflowModel,
        indexed_model: ModelWithLocation,
    ) -> None:
        download_sources = list(workflow_model.sources or [])

        manifest_model = ManifestModel(
            hash=indexed_model.hash,
            filename=indexed_model.filename,
            relative_path=indexed_model.relative_path,
            category=workflow_model.category,
            size=indexed_model.file_size,
            sources=download_sources,
        )
        self.models.add_model(manifest_model)

        workflow_models[workflow_model_index].hash = indexed_model.hash
        workflow_models[workflow_model_index].status = "resolved"
        workflow_models[workflow_model_index].sources = []
        workflow_models[workflow_model_index].relative_path = None
        self.workflows.set_workflow_models(workflow_name, workflow_models)

        logger.info(
            f"Updated model '{workflow_model.filename}' with hash {indexed_model.hash}"
        )
