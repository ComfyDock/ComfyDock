"""Unit tests for reusable environment readiness checks."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from comfygit_core.models.manifest import (
    EnvironmentManifestSnapshot,
    ManifestModel,
    ManifestProjectSnapshot,
    ManifestUVSnapshot,
    ManifestWorkflowEntry,
    ManifestWorkflowModel,
)
from comfygit_core.models.readiness import (
    ModelSourceCandidate,
    ModelSourceWarning,
    NodeProvenanceWarning,
    ReadinessContext,
    ReadinessWorkflowStatus,
)
from comfygit_core.models.shared import NodeInfo
from comfygit_core.models.workflow_contract import WorkflowExecutionContract
from comfygit_core.services.environment_readiness import (
    build_environment_readiness,
    collect_contract_artifact_blockers,
    collect_model_source_warnings,
    collect_node_provenance_warnings,
)


class FakeSourceReader:
    def __init__(self, sources_by_hash=None):
        self._sources_by_hash = sources_by_hash or {}

    def get_model_source_candidates(self, model_hash: str):
        return self._sources_by_hash.get(model_hash, [])


class FakeEnvironment:
    def __init__(
        self,
        *,
        snapshot: EnvironmentManifestSnapshot,
        cec_path: Path,
        model_sources=None,
        workflow_status=None,
        has_git_changes: bool = False,
    ) -> None:
        self._snapshot = snapshot
        self.cec_path = cec_path
        self._model_sources = model_sources or {}
        self._workflow_status = workflow_status
        self._has_git_changes = has_git_changes

    def get_manifest_snapshot(self) -> EnvironmentManifestSnapshot:
        return self._snapshot

    def get_workflow_status(self) -> ReadinessWorkflowStatus:
        if self._workflow_status is None:
            raise AssertionError("workflow status was not configured")
        return cast(ReadinessWorkflowStatus, self._workflow_status)

    def has_uncommitted_git_changes(self) -> bool:
        return self._has_git_changes

    def get_model_source_candidates(self, model_hash: str):
        return self._model_sources.get(model_hash, [])


def make_node(
    name: str,
    source: str,
    *,
    criticality: str = "required",
    version: str | None = "dev",
    repository: str | None = None,
    registry_id: str | None = None,
    pinned_commit: str | None = None,
) -> NodeInfo:
    return NodeInfo(
        name=name,
        source=source,
        criticality=criticality,
        version=version,
        repository=repository,
        registry_id=registry_id,
        pinned_commit=pinned_commit,
    )


def make_model(
    filename: str,
    *,
    hash: str = "abc123",
    sources: list[str] | None = None,
) -> ManifestModel:
    return ManifestModel(
        hash=hash,
        filename=filename,
        size=1,
        relative_path=filename,
        category="checkpoints",
        sources=sources or [],
    )


def make_workflow_model(
    filename: str,
    *,
    hash: str | None = "abc123",
    criticality: str = "required",
    sources: list[str] | None = None,
) -> ManifestWorkflowModel:
    return ManifestWorkflowModel(
        filename=filename,
        category="checkpoints",
        criticality=criticality,
        status="resolved",
        nodes=[],
        hash=hash,
        sources=sources or [],
    )


def make_snapshot(
    *,
    nodes=None,
    models=None,
    workflow_models=None,
    execution_contracts=None,
) -> EnvironmentManifestSnapshot:
    workflow_models = workflow_models or {}
    execution_contracts = execution_contracts or {}
    workflow_names = sorted(set(workflow_models) | set(execution_contracts))
    workflows = {
        name: ManifestWorkflowEntry(
            name=name,
            models=tuple(workflow_models.get(name, ())),
            execution_contract=execution_contracts.get(name),
        )
        for name in workflow_names
    }

    return EnvironmentManifestSnapshot(
        project=ManifestProjectSnapshot(),
        schema_version=1,
        comfyui_version=None,
        python_version=None,
        manifest_state="local",
        sync_extras=(),
        dependency_groups={},
        uv=ManifestUVSnapshot(),
        nodes={node.name: node for node in nodes or []},
        workflows=workflows,
        models={model.hash: model for model in models or []},
    )


def make_context(
    *,
    nodes=None,
    models=None,
    workflow_models=None,
    model_sources=None,
    execution_contracts=None,
    cec_path: Path | None = None,
) -> ReadinessContext:
    return ReadinessContext(
        manifest=make_snapshot(
            nodes=nodes,
            models=models,
            workflow_models=workflow_models,
            execution_contracts=execution_contracts,
        ),
        manifest_dir=cec_path or Path("."),
        model_source_reader=FakeSourceReader(model_sources),
    )


def make_env(
    *,
    nodes=None,
    models=None,
    workflow_models=None,
    model_sources=None,
    execution_contracts=None,
    cec_path: Path | None = None,
    workflow_status=None,
    git_changes: bool = False,
)-> FakeEnvironment:
    snapshot = make_snapshot(
        nodes=nodes,
        models=models,
        workflow_models=workflow_models,
        execution_contracts=execution_contracts,
    )
    return FakeEnvironment(
        snapshot=snapshot,
        cec_path=cec_path or Path("."),
        model_sources=model_sources,
        workflow_status=workflow_status,
        has_git_changes=git_changes,
    )


def test_optional_dev_nodes_are_excluded_from_provenance_warnings():
    context = make_context(
        nodes=[
            make_node(
                name="local-dev-node",
                source="development",
                criticality="optional",
                repository=None,
                pinned_commit=None,
            )
        ]
    )

    assert collect_node_provenance_warnings(context) == []


def test_required_dev_nodes_without_portable_source_are_reported():
    context = make_context(
        nodes=[
            make_node(
                name="local-dev-node",
                source="development",
                criticality="required",
                repository=None,
                pinned_commit=None,
            )
        ]
    )

    warnings = collect_node_provenance_warnings(context)

    assert len(warnings) == 1
    assert warnings[0] == NodeProvenanceWarning(
        name="local-dev-node",
        source="development",
        criticality="required",
        reason="Development node is missing portable git repository and pinned commit metadata.",
        version="dev",
    )


def test_model_without_manifest_or_repository_source_is_reported_once():
    model = make_model(filename="checkpoint.safetensors", hash="abc123", sources=[])
    context = make_context(
        models=[model],
        workflow_models={
            "simple": [
                make_workflow_model(filename="checkpoint.safetensors", hash="abc123")
            ],
        },
    )

    warnings = collect_model_source_warnings(context)

    assert warnings == [
        ModelSourceWarning(
            filename="checkpoint.safetensors",
            hash="abc123",
            criticality="required",
            workflows=["simple"],
        )
    ]


def test_model_source_warning_uses_workflow_criticality():
    model = make_model(filename="manual.safetensors", hash="abc123", sources=[])
    context = make_context(
        models=[model],
        workflow_models={
            "simple": [
                make_workflow_model(
                    filename="manual.safetensors",
                    hash="abc123",
                    criticality="optional",
                )
            ]
        },
    )

    warnings = collect_model_source_warnings(context)

    assert len(warnings) == 1
    assert warnings[0].criticality == "optional"


def test_indexed_model_sources_are_reported_as_repair_candidates():
    model = make_model(filename="checkpoint.safetensors", hash="abc123", sources=[])
    context = make_context(
        models=[model],
        workflow_models={
            "simple": [
                make_workflow_model(filename="checkpoint.safetensors", hash="abc123")
            ],
        },
        model_sources={
            "abc123": [
                ModelSourceCandidate(
                    type="huggingface",
                    url="https://example.test/model.safetensors",
                )
            ]
        },
    )

    assert collect_model_source_warnings(context) == [
        ModelSourceWarning(
            filename="checkpoint.safetensors",
            hash="abc123",
            criticality="required",
            workflows=["simple"],
            source_candidates=[
                ModelSourceCandidate(
                    type="huggingface",
                    url="https://example.test/model.safetensors",
                )
            ],
        )
    ]


def test_environment_adapter_uses_public_model_source_candidate_facade():
    model = make_model(filename="checkpoint.safetensors", hash="abc123", sources=[])
    sync_status = SimpleNamespace(
        has_changes=False,
        new=[],
        modified=[],
        deleted=[],
    )
    env = make_env(
        models=[model],
        workflow_models={
            "simple": [
                make_workflow_model(filename="checkpoint.safetensors", hash="abc123")
            ],
        },
        model_sources={
            "abc123": [
                {
                    "type": "huggingface",
                    "url": "https://example.test/model.safetensors",
                }
            ]
        },
        workflow_status=SimpleNamespace(sync_status=sync_status, is_commit_safe=True),
    )

    readiness = build_environment_readiness(env, include_blocking=True)

    assert readiness.warnings.models_without_sources[0].source_candidates == [
        ModelSourceCandidate(
            type="huggingface",
            url="https://example.test/model.safetensors",
        )
    ]


def test_blocking_source_state_can_be_included():
    sync_status = SimpleNamespace(
        has_changes=True,
        new=["new_workflow"],
        modified=[],
        deleted=[],
    )
    status = SimpleNamespace(sync_status=sync_status, is_commit_safe=True)
    env = make_env(workflow_status=status, git_changes=False)

    readiness = build_environment_readiness(env, include_blocking=True)

    assert readiness.can_export is False
    assert readiness.blocking_issues[0].type == "uncommitted_workflows"


def test_missing_referenced_contract_api_prompt_blocks_handoff(tmp_path):
    sync_status = SimpleNamespace(
        has_changes=False,
        new=[],
        modified=[],
        deleted=[],
    )
    env = make_env(
        execution_contracts={
            "simple": WorkflowExecutionContract(
                api_prompt_file="workflow_api/simple.api.json"
            )
        },
        cec_path=tmp_path,
        workflow_status=SimpleNamespace(sync_status=sync_status, is_commit_safe=True),
        git_changes=False,
    )

    readiness = build_environment_readiness(env, include_blocking=True)

    assert readiness.can_export is False
    assert readiness.blocking_issues[-1].type == "missing_contract_api_prompts"
    assert readiness.blocking_issues[-1].details == [
        "simple: workflow_api/simple.api.json"
    ]


def test_existing_referenced_contract_api_prompt_is_not_blocking(tmp_path):
    api_dir = tmp_path / "workflow_api"
    api_dir.mkdir()
    (api_dir / "simple.api.json").write_text("{}", encoding="utf-8")
    context = make_context(
        execution_contracts={
            "simple": WorkflowExecutionContract(
                api_prompt_file="workflow_api/simple.api.json"
            )
        },
        cec_path=tmp_path,
    )

    assert collect_contract_artifact_blockers(context) == []


def test_readiness_serializes_to_manager_api_shape():
    env = make_env(
        nodes=[
            make_node(
                name="local-dev-node",
                source="development",
                criticality="required",
                repository=None,
                pinned_commit=None,
            )
        ]
    )

    readiness = build_environment_readiness(env, include_blocking=False)

    assert readiness.to_dict() == {
        "can_export": True,
        "blocking_issues": [],
        "warnings": {
            "models_without_sources": [],
            "nodes_without_provenance": [
                {
                    "name": "local-dev-node",
                    "source": "development",
                    "criticality": "required",
                    "reason": (
                        "Development node is missing portable git repository "
                        "and pinned commit metadata."
                    ),
                    "registry_id": None,
                    "repository": None,
                    "version": "dev",
                    "pinned_commit": None,
                }
            ],
        },
    }
