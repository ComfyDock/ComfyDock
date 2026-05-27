from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel
from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.models.workflow import WorkflowNodeWidgetRef
from comfygit_core.services.workflow_model_dependency_service import (
    WorkflowModelDependencyService,
)


@dataclass
class InMemoryWorkflowModels:
    entries: dict[str, list[ManifestWorkflowModel]] = field(default_factory=dict)

    def get_workflow_models(
        self,
        workflow_name: str,
        config: dict | None = None,
    ) -> list[ManifestWorkflowModel]:
        return list(self.entries.get(workflow_name, []))

    def set_workflow_models(
        self,
        workflow_name: str,
        models: list[ManifestWorkflowModel],
        config: dict | None = None,
    ) -> None:
        self.entries[workflow_name] = list(models)


@dataclass
class InMemoryGlobalModels:
    entries: dict[str, ManifestModel] = field(default_factory=dict)

    def add_model(self, model: ManifestModel, config: dict | None = None) -> None:
        self.entries[model.hash] = model


@dataclass
class InMemoryModelRepository:
    entries: dict[str, ModelWithLocation] = field(default_factory=dict)

    def get_model(self, hash: str) -> ModelWithLocation | None:
        return self.entries.get(hash)


def _download_intent(ref: WorkflowNodeWidgetRef) -> ManifestWorkflowModel:
    return ManifestWorkflowModel(
        filename=ref.widget_value,
        category="checkpoints",
        criticality="required",
        status="unresolved",
        nodes=[ref],
        sources=["https://example.com/model.safetensors"],
        relative_path="checkpoints/model.safetensors",
    )


def test_mark_download_resolved_by_reference_adds_global_model_and_clears_intent():
    ref = WorkflowNodeWidgetRef(
        node_id="1",
        node_type="CheckpointLoaderSimple",
        widget_index=0,
        widget_value="model.safetensors",
    )
    workflows = InMemoryWorkflowModels({"flow": [_download_intent(ref)]})
    global_models = InMemoryGlobalModels()
    repository = InMemoryModelRepository(
        {
            "abc123": ModelWithLocation(
                hash="abc123",
                filename="model.safetensors",
                relative_path="checkpoints/model.safetensors",
                file_size=42,
                mtime=0,
                last_seen=1,
            )
        }
    )

    service = WorkflowModelDependencyService(
        workflows=workflows,
        models=global_models,
        model_repository=repository,
    )

    service.mark_download_resolved_by_reference("flow", ref, "abc123")

    assert global_models.entries["abc123"] == ManifestModel(
        hash="abc123",
        filename="model.safetensors",
        size=42,
        relative_path="checkpoints/model.safetensors",
        category="checkpoints",
        sources=["https://example.com/model.safetensors"],
    )
    resolved = workflows.entries["flow"][0]
    assert resolved.hash == "abc123"
    assert resolved.status == "resolved"
    assert resolved.sources == []
    assert resolved.relative_path is None


def test_mark_download_resolved_by_filename_preserves_intent_when_indexed_model_missing():
    ref = WorkflowNodeWidgetRef(
        node_id="1",
        node_type="CheckpointLoaderSimple",
        widget_index=0,
        widget_value="model.safetensors",
    )
    intent = _download_intent(ref)
    workflows = InMemoryWorkflowModels({"flow": [intent]})
    service = WorkflowModelDependencyService(
        workflows=workflows,
        models=InMemoryGlobalModels(),
        model_repository=InMemoryModelRepository(),
    )

    changed = service.mark_download_resolved_by_filename(
        "flow",
        filename="model.safetensors",
        model_hash="missing",
    )

    assert changed is False
    assert workflows.entries["flow"][0].sources == ["https://example.com/model.safetensors"]
    assert workflows.entries["flow"][0].status == "unresolved"


def test_mark_download_resolved_by_reference_raises_when_indexed_model_missing():
    ref = WorkflowNodeWidgetRef(
        node_id="1",
        node_type="CheckpointLoaderSimple",
        widget_index=0,
        widget_value="model.safetensors",
    )
    workflows = InMemoryWorkflowModels({"flow": [_download_intent(ref)]})
    service = WorkflowModelDependencyService(
        workflows=workflows,
        models=InMemoryGlobalModels(),
        model_repository=InMemoryModelRepository(),
    )

    with pytest.raises(ValueError, match="not found in repository"):
        service.mark_download_resolved_by_reference("flow", ref, "missing")

    assert workflows.entries["flow"][0].sources == ["https://example.com/model.safetensors"]
    assert workflows.entries["flow"][0].status == "unresolved"


def test_update_criticality_updates_all_matching_workflow_models():
    ref = WorkflowNodeWidgetRef(
        node_id="1",
        node_type="CheckpointLoaderSimple",
        widget_index=0,
        widget_value="model.safetensors",
    )
    first = _download_intent(ref)
    first.hash = "same-hash"
    second = _download_intent(ref)
    second.hash = "same-hash"
    workflows = InMemoryWorkflowModels({"flow": [first, second]})
    service = WorkflowModelDependencyService(
        workflows=workflows,
        models=InMemoryGlobalModels(),
        model_repository=InMemoryModelRepository(),
    )

    assert service.update_criticality("flow", "same-hash", "optional") is True
    assert [model.criticality for model in workflows.entries["flow"]] == [
        "optional",
        "optional",
    ]
