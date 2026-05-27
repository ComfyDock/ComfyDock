from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import Mock

from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.models.workflow import (
    BatchDownloadCallbacks,
    ResolutionResult,
    ResolvedModel,
    WorkflowNodeWidgetRef,
)
from comfygit_core.services.model_downloader import (
    DownloadRequest,
)
from comfygit_core.services.model_downloader import (
    DownloadResult as ModelDownloadResult,
)
from comfygit_core.services.workflow_model_download_coordinator import (
    WorkflowModelDownloadCoordinator,
)


@dataclass
class FakeDownloader:
    models_dir: Path
    result: ModelDownloadResult | None = None
    requests: list[DownloadRequest] = field(default_factory=list)

    def download(self, request, progress_callback=None) -> ModelDownloadResult:
        self.requests.append(request)
        if progress_callback:
            progress_callback(1, 2)
        return self.result or ModelDownloadResult(
            success=False,
            error="not configured",
        )


@dataclass
class FakeSourceLookup:
    by_url: dict[str, ModelWithLocation] = field(default_factory=dict)

    def find_by_source_url(self, url: str) -> ModelWithLocation | None:
        return self.by_url.get(url)


@dataclass
class FakeDependencyUpdater:
    error: Exception | None = None
    calls: list[tuple[str, WorkflowNodeWidgetRef, str]] = field(default_factory=list)

    def mark_download_resolved_by_reference(
        self,
        workflow_name: str,
        reference: WorkflowNodeWidgetRef,
        model_hash: str,
    ) -> None:
        if self.error:
            raise self.error
        self.calls.append((workflow_name, reference, model_hash))


def _model(model_hash: str = "abc123") -> ModelWithLocation:
    return ModelWithLocation(
        hash=model_hash,
        filename="model.safetensors",
        relative_path="checkpoints/model.safetensors",
        file_size=42,
        mtime=0,
        last_seen=1,
    )


def _reference(filename: str = "model.safetensors") -> WorkflowNodeWidgetRef:
    return WorkflowNodeWidgetRef(
        node_id="1",
        node_type="CheckpointLoaderSimple",
        widget_index=0,
        widget_value=filename,
    )


def _resolution(
    *,
    model_source: str | None = "https://example.com/model.safetensors",
    target_path: Path | None = Path("checkpoints/model.safetensors"),
) -> ResolutionResult:
    return ResolutionResult(
        workflow_name="flow",
        models_resolved=[
            ResolvedModel(
                workflow="flow",
                reference=_reference(),
                resolved_model=None,
                model_source=model_source,
                match_type="download_intent",
                target_path=target_path,
            )
        ],
    )


@dataclass(frozen=True)
class CallbackMocks:
    callbacks: BatchDownloadCallbacks
    batch_start: Mock
    file_start: Mock
    file_progress: Mock
    file_complete: Mock
    batch_complete: Mock


def _callbacks() -> CallbackMocks:
    batch_start = Mock()
    file_start = Mock()
    file_progress = Mock()
    file_complete = Mock()
    batch_complete = Mock()
    return CallbackMocks(
        callbacks=BatchDownloadCallbacks(
            on_batch_start=batch_start,
            on_file_start=file_start,
            on_file_progress=file_progress,
            on_file_complete=file_complete,
            on_batch_complete=batch_complete,
        ),
        batch_start=batch_start,
        file_start=file_start,
        file_progress=file_progress,
        file_complete=file_complete,
        batch_complete=batch_complete,
    )


def test_reuses_existing_source_and_updates_manifest():
    existing = _model()
    dependencies = FakeDependencyUpdater()
    coordinator = WorkflowModelDownloadCoordinator(
        downloader=FakeDownloader(Path("/models")),
        model_sources=FakeSourceLookup({"https://example.com/model.safetensors": existing}),
        dependencies=dependencies,
    )
    callback_mocks = _callbacks()

    results = coordinator.execute_pending_downloads(
        _resolution(),
        callback_mocks.callbacks,
    )

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].reused is True
    assert results[0].model is existing
    assert dependencies.calls == [("flow", _reference(), "abc123")]
    callback_mocks.file_complete.assert_called_once_with("model.safetensors", True, None)
    callback_mocks.batch_complete.assert_called_once_with(1, 1)


def test_missing_download_source_or_target_returns_failed_result_and_completes_batch():
    coordinator = WorkflowModelDownloadCoordinator(
        downloader=FakeDownloader(Path("/models")),
        model_sources=FakeSourceLookup(),
        dependencies=FakeDependencyUpdater(),
    )
    callback_mocks = _callbacks()

    results = coordinator.execute_pending_downloads(
        _resolution(model_source=None),
        callback_mocks.callbacks,
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error == "Download intent missing target_path or model_source"
    callback_mocks.file_complete.assert_called_once_with(
        "model.safetensors",
        False,
        "Download intent missing target_path or model_source",
    )
    callback_mocks.batch_complete.assert_called_once_with(0, 1)


def test_manifest_update_failure_after_reuse_returns_failed_result_and_completes_batch():
    coordinator = WorkflowModelDownloadCoordinator(
        downloader=FakeDownloader(Path("/models")),
        model_sources=FakeSourceLookup(
            {"https://example.com/model.safetensors": _model()}
        ),
        dependencies=FakeDependencyUpdater(error=ValueError("manifest update failed")),
    )
    callback_mocks = _callbacks()

    results = coordinator.execute_pending_downloads(
        _resolution(),
        callback_mocks.callbacks,
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error == "manifest update failed"
    callback_mocks.file_complete.assert_called_once_with(
        "model.safetensors",
        False,
        "manifest update failed",
    )
    callback_mocks.batch_complete.assert_called_once_with(0, 1)


def test_download_success_manifest_update_failure_returns_failed_result_and_completes_batch():
    downloader = FakeDownloader(
        Path("/models"),
        result=ModelDownloadResult(success=True, model=_model("downloaded")),
    )
    coordinator = WorkflowModelDownloadCoordinator(
        downloader=downloader,
        model_sources=FakeSourceLookup(),
        dependencies=FakeDependencyUpdater(error=ValueError("manifest update failed")),
    )
    callback_mocks = _callbacks()

    results = coordinator.execute_pending_downloads(
        _resolution(),
        callback_mocks.callbacks,
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error == "manifest update failed"
    assert downloader.requests[0].target_path == Path("/models/checkpoints/model.safetensors")
    callback_mocks.file_progress.assert_called_once_with(1, 2)
    callback_mocks.file_complete.assert_called_once_with(
        "model.safetensors",
        False,
        "manifest update failed",
    )
    callback_mocks.batch_complete.assert_called_once_with(0, 1)
