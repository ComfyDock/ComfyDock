"""Pending workflow model download execution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ..logging.logging_config import get_logger
from ..models.workflow import (
    BatchDownloadCallbacks,
    ResolutionResult,
)
from ..models.workflow import (
    DownloadResult as WorkflowDownloadResult,
)
from .model_downloader import DownloadRequest
from .model_downloader import (
    DownloadResult as ModelDownloadResult,
)

logger = get_logger(__name__)

if TYPE_CHECKING:
    from ..models.manifest import ManifestWorkflowModel
    from ..models.shared import ModelWithLocation
    from ..models.workflow import WorkflowNodeWidgetRef


class ModelSourceLookupProtocol(Protocol):
    """Model repository source lookup needed by pending download execution."""

    def find_by_source_url(self, url: str) -> ModelWithLocation | None:
        """Return an indexed model already associated with a source URL."""
        ...


class ModelDownloaderProtocol(Protocol):
    """Downloader operations needed by pending workflow downloads."""

    models_dir: Path

    def download(
        self,
        request: DownloadRequest,
        progress_callback=None,
    ) -> ModelDownloadResult:
        """Download one model file."""
        ...


class WorkflowModelDependencyUpdateProtocol(Protocol):
    """Workflow model manifest update needed after a download/reuse succeeds."""

    def mark_download_resolved_by_reference(
        self,
        workflow_name: str,
        reference: WorkflowNodeWidgetRef,
        model_hash: str,
    ) -> None:
        """Mark a workflow model download intent as resolved."""
        ...

    def mark_download_resolved_by_filename(
        self,
        workflow_name: str,
        *,
        filename: str,
        model_hash: str,
    ) -> bool:
        """Mark a manifest-only workflow model download intent as resolved."""
        ...


class WorkflowModelDownloadCoordinator:
    """Executes pending model download intents from workflow resolution results."""

    def __init__(
        self,
        *,
        downloader: ModelDownloaderProtocol,
        model_sources: ModelSourceLookupProtocol,
        dependencies: WorkflowModelDependencyUpdateProtocol,
    ) -> None:
        self.downloader = downloader
        self.model_sources = model_sources
        self.dependencies = dependencies

    def execute_pending_downloads(
        self,
        result: ResolutionResult,
        callbacks: BatchDownloadCallbacks | None = None,
    ) -> list[WorkflowDownloadResult]:
        """Execute all pending download intents in a resolution result."""
        intents = [
            resolved for resolved in result.models_resolved
            if resolved.match_type in ("download_intent", "property_download_intent")
        ]
        if not intents:
            return []

        if callbacks and callbacks.on_batch_start:
            callbacks.on_batch_start(len(intents))

        results: list[WorkflowDownloadResult] = []
        for idx, resolved in enumerate(intents, 1):
            filename = resolved.reference.widget_value
            if callbacks and callbacks.on_file_start:
                callbacks.on_file_start(filename, idx, len(intents))

            existing = (
                self.model_sources.find_by_source_url(resolved.model_source)
                if resolved.model_source
                else None
            )
            if existing is not None:
                update_error = self._mark_download_resolved(
                    result.workflow_name,
                    resolved.reference,
                    existing.hash,
                )
                if update_error is not None:
                    if callbacks and callbacks.on_file_complete:
                        callbacks.on_file_complete(filename, False, update_error)
                    results.append(
                        WorkflowDownloadResult(
                            success=False,
                            filename=filename,
                            error=update_error,
                        )
                    )
                    continue

                if callbacks and callbacks.on_file_complete:
                    callbacks.on_file_complete(filename, True, None)
                results.append(
                    WorkflowDownloadResult(
                        success=True,
                        filename=filename,
                        model=existing,
                        reused=True,
                    )
                )
                continue

            if not resolved.target_path or not resolved.model_source:
                error_msg = "Download intent missing target_path or model_source"
                if callbacks and callbacks.on_file_complete:
                    callbacks.on_file_complete(filename, False, error_msg)
                results.append(
                    WorkflowDownloadResult(
                        success=False,
                        filename=filename,
                        error=error_msg,
                    )
                )
                continue

            download_result = self._download_one(
                result.workflow_name,
                source_url=resolved.model_source,
                target_path=resolved.target_path,
                callbacks=callbacks,
            )

            if download_result.success and download_result.model:
                update_error = self._mark_download_resolved(
                    result.workflow_name,
                    resolved.reference,
                    download_result.model.hash,
                )
                if update_error is None and callbacks and callbacks.on_file_complete:
                    callbacks.on_file_complete(filename, True, None)
                elif update_error is not None:
                    if callbacks and callbacks.on_file_complete:
                        callbacks.on_file_complete(filename, False, update_error)
                    results.append(
                        WorkflowDownloadResult(
                            success=False,
                            filename=filename,
                            error=update_error,
                        )
                    )
                    continue
            else:
                if callbacks and callbacks.on_file_complete:
                    callbacks.on_file_complete(filename, False, download_result.error)

            results.append(
                WorkflowDownloadResult(
                    success=download_result.success,
                    filename=filename,
                    model=download_result.model if download_result.success else None,
                    error=download_result.error if not download_result.success else None,
                )
            )

        if callbacks and callbacks.on_batch_complete:
            success_count = sum(1 for item in results if item.success)
            callbacks.on_batch_complete(success_count, len(results))

        return results

    def execute_manifest_downloads(
        self,
        workflow_name: str,
        models: list[ManifestWorkflowModel],
        callbacks: BatchDownloadCallbacks | None = None,
    ) -> list[WorkflowDownloadResult]:
        """Download manual declarations that opaque custom loaders cannot expose."""
        intents = [
            model
            for model in models
            if model.declared_by == "manual"
            and model.status == "unresolved"
            and bool(model.sources)
            and bool(model.relative_path)
        ]
        if not intents:
            return []

        if callbacks and callbacks.on_batch_start:
            callbacks.on_batch_start(len(intents))

        results: list[WorkflowDownloadResult] = []
        for idx, model in enumerate(intents, 1):
            filename = model.filename
            source_url = model.sources[0]
            target_path = Path(model.relative_path or filename)
            if callbacks and callbacks.on_file_start:
                callbacks.on_file_start(filename, idx, len(intents))

            existing = self.model_sources.find_by_source_url(source_url)
            if existing is not None:
                update_error = self._manifest_hash_error(model, existing.hash)
                if update_error is None:
                    update_error = self._mark_manifest_download_resolved(
                        workflow_name,
                        filename=filename,
                        model_hash=existing.hash,
                    )
                success = update_error is None
                if callbacks and callbacks.on_file_complete:
                    callbacks.on_file_complete(filename, success, update_error)
                results.append(
                    WorkflowDownloadResult(
                        success=success,
                        filename=filename,
                        model=existing if success else None,
                        error=update_error,
                        reused=success,
                    )
                )
                continue

            download_result = self._download_one(
                workflow_name,
                source_url=source_url,
                target_path=target_path,
                callbacks=callbacks,
            )
            update_error = None
            if download_result.success and download_result.model:
                update_error = self._manifest_hash_error(
                    model,
                    download_result.model.hash,
                )
                if update_error is None:
                    update_error = self._mark_manifest_download_resolved(
                        workflow_name,
                        filename=filename,
                        model_hash=download_result.model.hash,
                    )

            success = download_result.success and update_error is None
            error = update_error or download_result.error
            if callbacks and callbacks.on_file_complete:
                callbacks.on_file_complete(filename, success, error)
            results.append(
                WorkflowDownloadResult(
                    success=success,
                    filename=filename,
                    model=download_result.model if success else None,
                    error=error if not success else None,
                )
            )

        if callbacks and callbacks.on_batch_complete:
            success_count = sum(1 for item in results if item.success)
            callbacks.on_batch_complete(success_count, len(results))

        return results

    @staticmethod
    def _manifest_hash_error(
        model: ManifestWorkflowModel,
        actual_hash: str,
    ) -> str | None:
        if model.hash and model.hash != actual_hash:
            return (
                f"Downloaded model hash mismatch for {model.filename}: "
                f"expected {model.hash}, found {actual_hash}"
            )
        return None

    def _download_one(
        self,
        workflow_name: str,
        *,
        source_url: str,
        target_path: Path,
        callbacks: BatchDownloadCallbacks | None,
    ) -> ModelDownloadResult:
        request = DownloadRequest(
            url=source_url,
            target_path=self.downloader.models_dir / target_path,
            workflow_name=workflow_name,
        )
        progress_callback = callbacks.on_file_progress if callbacks else None
        return self.downloader.download(
            request,
            progress_callback=progress_callback,
        )

    def _mark_download_resolved(
        self,
        workflow_name: str,
        reference: WorkflowNodeWidgetRef,
        model_hash: str,
    ) -> str | None:
        try:
            self.dependencies.mark_download_resolved_by_reference(
                workflow_name,
                reference,
                model_hash,
            )
        except Exception as exc:
            logger.warning(
                "Downloaded model was indexed but workflow manifest update failed: %s",
                exc,
            )
            return str(exc)
        return None

    def _mark_manifest_download_resolved(
        self,
        workflow_name: str,
        *,
        filename: str,
        model_hash: str,
    ) -> str | None:
        try:
            changed = self.dependencies.mark_download_resolved_by_filename(
                workflow_name,
                filename=filename,
                model_hash=model_hash,
            )
            if not changed:
                return f"Workflow model download intent not found: {filename}"
        except Exception as exc:
            logger.warning(
                "Downloaded model was indexed but manual workflow manifest update failed: %s",
                exc,
            )
            return str(exc)
        return None
