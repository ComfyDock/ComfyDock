"""Unit tests for reusable environment readiness checks."""

from dataclasses import dataclass
from types import SimpleNamespace

from comfygit_core.models.readiness import ModelSourceWarning, NodeProvenanceWarning
from comfygit_core.services.environment_readiness import (
    build_environment_readiness,
    collect_contract_artifact_blockers,
    collect_model_source_warnings,
    collect_node_provenance_warnings,
)


@dataclass
class FakeNode:
    name: str
    source: str
    criticality: str = "required"
    version: str | None = "dev"
    repository: str | None = None
    registry_id: str | None = None
    pinned_commit: str | None = None


@dataclass
class FakeModel:
    filename: str
    hash: str | None = None
    criticality: str = "required"
    sources: list[str] | None = None


class FakeNodesManager:
    def __init__(self, nodes):
        self._nodes = nodes

    def get_existing(self):
        return {node.name: node for node in self._nodes}


class FakeModelsManager:
    def __init__(self, models):
        self._models = models

    def get_all(self):
        return {model.hash or model.filename: model for model in self._models}


class FakeWorkflowsManager:
    def __init__(self, workflows=None, workflow_models=None, execution_contracts=None):
        self._workflows = workflows or {}
        self._workflow_models = workflow_models or {}
        self._execution_contracts = execution_contracts or {}

    def get_all_with_resolutions(self):
        return self._workflows

    def get_workflow_models(self, name):
        return self._workflow_models.get(name, [])

    def get_execution_contract(self, name):
        return self._execution_contracts.get(name)


class FakeModelRepository:
    def __init__(self, sources_by_hash=None):
        self._sources_by_hash = sources_by_hash or {}

    def get_sources(self, model_hash):
        return self._sources_by_hash.get(model_hash, [])


class FakeGitManager:
    def __init__(self, has_changes=False):
        self._has_changes = has_changes

    def has_uncommitted_changes(self):
        return self._has_changes


class FakeWorkflowManager:
    def __init__(self, status):
        self._status = status

    def get_workflow_status(self):
        return self._status


def make_env(
    nodes=None,
    models=None,
    workflows=None,
    workflow_models=None,
    model_sources=None,
    execution_contracts=None,
    cec_path=None,
):
    return SimpleNamespace(
        cec_path=cec_path,
        pyproject=SimpleNamespace(
            nodes=FakeNodesManager(nodes or []),
            models=FakeModelsManager(models or []),
            workflows=FakeWorkflowsManager(workflows, workflow_models, execution_contracts),
        ),
        workspace=SimpleNamespace(model_repository=FakeModelRepository(model_sources)),
    )


def test_optional_dev_nodes_are_excluded_from_provenance_warnings():
    env = make_env(
        nodes=[
            FakeNode(
                name="local-dev-node",
                source="development",
                criticality="optional",
                repository=None,
                pinned_commit=None,
            )
        ]
    )

    assert collect_node_provenance_warnings(env) == []


def test_required_dev_nodes_without_portable_source_are_reported():
    env = make_env(
        nodes=[
            FakeNode(
                name="local-dev-node",
                source="development",
                criticality="required",
                repository=None,
                pinned_commit=None,
            )
        ]
    )

    warnings = collect_node_provenance_warnings(env)

    assert len(warnings) == 1
    assert warnings[0] == NodeProvenanceWarning(
        name="local-dev-node",
        source="development",
        criticality="required",
        reason="Development node is missing portable git repository and pinned commit metadata.",
        version="dev",
    )


def test_model_without_manifest_or_repository_source_is_reported_once():
    model = FakeModel(filename="checkpoint.safetensors", hash="abc123", sources=[])
    env = make_env(
        models=[model],
        workflows={"simple": object()},
        workflow_models={"simple": [FakeModel(filename="checkpoint.safetensors", hash="abc123")]},
    )

    warnings = collect_model_source_warnings(env)

    assert warnings == [
        ModelSourceWarning(
            filename="checkpoint.safetensors",
            hash="abc123",
            criticality="required",
            workflows=["simple"],
        )
    ]


def test_model_source_warning_uses_workflow_criticality():
    model = FakeModel(filename="manual.safetensors", hash="abc123", sources=[])
    env = make_env(
        models=[model],
        workflows={"simple": object()},
        workflow_models={
            "simple": [
                FakeModel(
                    filename="manual.safetensors",
                    hash="abc123",
                    criticality="optional",
                )
            ]
        },
    )

    warnings = collect_model_source_warnings(env)

    assert len(warnings) == 1
    assert warnings[0].criticality == "optional"


def test_model_repository_sources_are_reported_as_repair_candidates():
    model = FakeModel(filename="checkpoint.safetensors", hash="abc123", sources=[])
    env = make_env(
        models=[model],
        workflows={"simple": object()},
        workflow_models={"simple": [FakeModel(filename="checkpoint.safetensors", hash="abc123")]},
        model_sources={
            "abc123": [
                {
                    "type": "huggingface",
                    "url": "https://example.test/model.safetensors",
                }
            ]
        },
    )

    assert collect_model_source_warnings(env) == [
        ModelSourceWarning(
            filename="checkpoint.safetensors",
            hash="abc123",
            criticality="required",
            workflows=["simple"],
            source_candidates=[
                {
                    "type": "huggingface",
                    "url": "https://example.test/model.safetensors",
                }
            ],
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
    env = make_env()
    env.workflow_manager = FakeWorkflowManager(status)
    env.git_manager = FakeGitManager(has_changes=False)

    readiness = build_environment_readiness(env, include_blocking=True)

    assert readiness.can_export is False
    assert readiness.blocking_issues[0].type == "uncommitted_workflows"


def test_missing_referenced_contract_api_prompt_blocks_handoff(tmp_path):
    env = make_env(
        workflows={"simple": object()},
        execution_contracts={
            "simple": SimpleNamespace(api_prompt_file="workflow_api/simple.api.json")
        },
        cec_path=tmp_path,
    )
    sync_status = SimpleNamespace(
        has_changes=False,
        new=[],
        modified=[],
        deleted=[],
    )
    env.workflow_manager = FakeWorkflowManager(
        SimpleNamespace(sync_status=sync_status, is_commit_safe=True)
    )
    env.git_manager = FakeGitManager(has_changes=False)

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
    env = make_env(
        workflows={"simple": object()},
        execution_contracts={
            "simple": SimpleNamespace(api_prompt_file="workflow_api/simple.api.json")
        },
        cec_path=tmp_path,
    )

    assert collect_contract_artifact_blockers(env) == []


def test_readiness_serializes_to_manager_api_shape():
    env = make_env(
        nodes=[
            FakeNode(
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
