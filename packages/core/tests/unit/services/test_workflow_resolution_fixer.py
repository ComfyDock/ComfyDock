from __future__ import annotations

from dataclasses import dataclass, field

from comfygit_core.models.manifest import ManifestModel
from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.models.workflow import (
    ModelResolutionContext,
    NodeResolutionContext,
    ResolutionResult,
    ResolvedModel,
    ResolvedNodePackage,
    WorkflowNode,
    WorkflowNodeWidgetRef,
)
from comfygit_core.services.workflow_resolution_fixer import WorkflowResolutionFixer


@dataclass
class FakeNodes:
    existing: dict = field(default_factory=dict)

    def get_existing(self) -> dict:
        return self.existing


@dataclass
class FakeWorkflows:
    custom_map: dict[str, str | bool] = field(default_factory=dict)
    mappings: list[tuple[str, str, str | None]] = field(default_factory=list)

    def get_custom_node_map(self, workflow_name: str, config: dict | None = None) -> dict:
        return self.custom_map

    def set_custom_node_mapping(
        self,
        workflow_name: str,
        node_type: str,
        package_id: str | None,
    ) -> None:
        self.mappings.append((workflow_name, node_type, package_id))


@dataclass
class FakeModels:
    entries: list[ManifestModel] = field(default_factory=list)

    def get_all(self) -> list[ManifestModel]:
        return self.entries


@dataclass
class FixerRecorder:
    node_writes: list[tuple[str, str]] = field(default_factory=list)
    model_writes: list[tuple[str, ResolvedModel, list[WorkflowNodeWidgetRef]]] = field(default_factory=list)
    path_updates: list[ResolutionResult] = field(default_factory=list)

    def write_node(self, workflow_name: str, package_id: str) -> None:
        self.node_writes.append((workflow_name, package_id))

    def write_model(
        self,
        workflow_name: str,
        resolved: ResolvedModel,
        refs: list[WorkflowNodeWidgetRef],
    ) -> None:
        self.model_writes.append((workflow_name, resolved, refs))

    def update_paths(self, result: ResolutionResult) -> int:
        self.path_updates.append(result)
        return 0


class SelectNodeStrategy:
    def __init__(self, selected: ResolvedNodePackage | None) -> None:
        self.selected = selected
        self.calls: list[tuple[str, list[ResolvedNodePackage], NodeResolutionContext]] = []

    def resolve_unknown_node(
        self,
        node_type: str,
        possible: list[ResolvedNodePackage],
        context: NodeResolutionContext,
    ) -> ResolvedNodePackage | None:
        self.calls.append((node_type, possible, context))
        return self.selected

    def confirm_node_install(self, package: ResolvedNodePackage) -> bool:
        return True


class SelectModelStrategy:
    def __init__(self, selected: ResolvedModel | None) -> None:
        self.selected = selected
        self.calls: list[tuple[WorkflowNodeWidgetRef, list[ResolvedModel], ModelResolutionContext]] = []

    def resolve_model(
        self,
        reference: WorkflowNodeWidgetRef,
        candidates: list[ResolvedModel],
        context: ModelResolutionContext,
    ) -> ResolvedModel | None:
        self.calls.append((reference, candidates, context))
        return self.selected


class RaisingModelStrategy(SelectModelStrategy):
    def resolve_model(
        self,
        reference: WorkflowNodeWidgetRef,
        candidates: list[ResolvedModel],
        context: ModelResolutionContext,
    ) -> ResolvedModel | None:
        self.calls.append((reference, candidates, context))
        raise RuntimeError("strategy failed")


def _ref(node_id: str = "1") -> WorkflowNodeWidgetRef:
    return WorkflowNodeWidgetRef(
        node_id=node_id,
        node_type="CheckpointLoaderSimple",
        widget_index=0,
        widget_value="model.safetensors",
    )


def _fixer(
    recorder: FixerRecorder,
    *,
    workflows: FakeWorkflows | None = None,
    models: FakeModels | None = None,
) -> WorkflowResolutionFixer:
    return WorkflowResolutionFixer(
        nodes=FakeNodes(),
        workflows=workflows or FakeWorkflows(),
        models=models or FakeModels(),
        search_packages=lambda *args, **kwargs: [],
        search_models=lambda query, node_type=None, limit=9: [],
        downloader=None,
        consensus_custom_node_map=lambda workflow_name: {},
        normalize_package_id=lambda package_id: f"normalized-{package_id}",
        write_single_node_resolution=recorder.write_node,
        write_model_resolution_grouped=recorder.write_model,
        update_workflow_model_paths=recorder.update_paths,
    )


def test_fix_resolution_without_strategies_preserves_unresolved_items():
    recorder = FixerRecorder()
    unresolved_node = WorkflowNode(id="7", type="MissingNode")
    unresolved_model = _ref()
    resolution = ResolutionResult(
        workflow_name="flow",
        nodes_unresolved=[unresolved_node],
        models_unresolved=[unresolved_model],
    )

    result = _fixer(recorder).fix_resolution(resolution)

    assert result.nodes_unresolved == [unresolved_node]
    assert result.models_unresolved == [unresolved_model]
    assert recorder.node_writes == []
    assert recorder.model_writes == []
    assert recorder.path_updates == [result]


def test_fix_resolution_writes_user_confirmed_node_mapping_progressively():
    recorder = FixerRecorder()
    workflows = FakeWorkflows()
    selected = ResolvedNodePackage(
        node_type="MissingNode",
        match_type="manual",
        package_id="pkg",
    )
    strategy = SelectNodeStrategy(selected)
    resolution = ResolutionResult(
        workflow_name="flow",
        nodes_unresolved=[WorkflowNode(id="7", type="MissingNode")],
    )

    result = _fixer(recorder, workflows=workflows).fix_resolution(
        resolution,
        node_strategy=strategy,
    )

    assert result.nodes_resolved == [selected]
    assert result.nodes_unresolved == []
    assert workflows.mappings == [("flow", "MissingNode", "normalized-pkg")]
    assert recorder.node_writes == [("flow", "normalized-pkg")]


def test_fix_resolution_marks_node_optional_without_installing_package():
    recorder = FixerRecorder()
    workflows = FakeWorkflows()
    selected = ResolvedNodePackage(
        node_type="OptionalNode",
        match_type="optional",
        package_id="pkg",
    )
    resolution = ResolutionResult(
        workflow_name="flow",
        nodes_unresolved=[WorkflowNode(id="7", type="OptionalNode")],
    )

    result = _fixer(recorder, workflows=workflows).fix_resolution(
        resolution,
        node_strategy=SelectNodeStrategy(selected),
    )

    assert result.nodes_resolved == []
    assert result.nodes_unresolved == []
    assert workflows.mappings == [("flow", "OptionalNode", None)]
    assert recorder.node_writes == []


def test_fix_resolution_deduplicates_model_strategy_prompt_and_writes_all_refs():
    recorder = FixerRecorder()
    ref_a = _ref("1")
    ref_b = _ref("2")
    resolved_model = ModelWithLocation(
        hash="abc123",
        filename="model.safetensors",
        relative_path="checkpoints/model.safetensors",
        file_size=42,
        mtime=0,
        last_seen=1,
    )
    selected = ResolvedModel(
        workflow="flow",
        reference=ref_a,
        resolved_model=resolved_model,
        match_type="exact",
    )
    strategy = SelectModelStrategy(selected)
    resolution = ResolutionResult(
        workflow_name="flow",
        models_unresolved=[ref_a, ref_b],
    )

    result = _fixer(recorder).fix_resolution(
        resolution,
        model_strategy=strategy,
    )

    assert len(strategy.calls) == 1
    assert recorder.model_writes == [("flow", selected, [ref_a, ref_b])]
    assert [resolved.reference for resolved in result.models_resolved] == [ref_a, ref_b]
    assert result.models_unresolved == []


def test_fix_resolution_populates_global_model_context():
    recorder = FixerRecorder()
    ref = _ref()
    manifest_model = ManifestModel(
        hash="abc123",
        filename="model.safetensors",
        size=42,
        relative_path="checkpoints/model.safetensors",
        category="checkpoints",
    )
    strategy = SelectModelStrategy(None)
    resolution = ResolutionResult(
        workflow_name="flow",
        models_unresolved=[ref],
    )

    _fixer(recorder, models=FakeModels([manifest_model])).fix_resolution(
        resolution,
        model_strategy=strategy,
    )

    assert strategy.calls[0][2].global_models == {"abc123": manifest_model}


def test_fix_resolution_keeps_model_unresolved_when_strategy_fails():
    recorder = FixerRecorder()
    ref = _ref()
    resolution = ResolutionResult(
        workflow_name="flow",
        models_unresolved=[ref],
    )

    result = _fixer(recorder).fix_resolution(
        resolution,
        model_strategy=RaisingModelStrategy(None),
    )

    assert result.models_resolved == []
    assert result.models_unresolved == [ref]
    assert recorder.model_writes == []
