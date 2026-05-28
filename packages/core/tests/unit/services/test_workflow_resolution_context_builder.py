from types import SimpleNamespace
from unittest.mock import Mock

from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel
from comfygit_core.models.shared import NodeInfo
from comfygit_core.models.workflow import (
    WorkflowDependencies,
    WorkflowNode,
    WorkflowNodeWidgetRef,
)
from comfygit_core.services.workflow_resolution_context_builder import (
    WorkflowResolutionContextBuilder,
)


def _pyproject() -> Mock:
    pyproject = Mock()
    pyproject.workflows.get_custom_node_map.return_value = {}
    pyproject.workflows.get_workflow_models.return_value = []
    pyproject.workflows.get_all_with_resolutions.return_value = {}
    pyproject.nodes.get_existing.return_value = {}
    pyproject.models.get_all.return_value = []
    return pyproject


def test_runtime_context_normalizes_and_filters_consensus_custom_node_mappings():
    pyproject = _pyproject()
    pyproject.nodes.get_existing.return_value = {
        "comfyui-deforum": NodeInfo(
            name="ComfyUI-Deforum",
            registry_id="comfyui-deforum",
            source="development",
        )
    }
    pyproject.workflows.get_all_with_resolutions.return_value = {
        "existing": {
            "custom_node_map": {
                "DeforumGetNode": "ComfyUI-Deforum",
                "UnknownNode": "unknown-package",
                "OptionalNode": False,
            }
        },
        "new": {},
    }
    pyproject.workflows.get_custom_node_map.return_value = {"LocalNode": "local-package"}

    builder = WorkflowResolutionContextBuilder(
        pyproject=pyproject,
        model_repository=Mock(),
        cec_path=None,
        builtin_versions_repository=None,
        normalize_package_id=lambda package_id: package_id.lower(),
    )

    context = builder.build_runtime_context(WorkflowDependencies(workflow_name="new"))

    assert context.custom_node_mappings == {
        "DeforumGetNode": "comfyui-deforum",
        "OptionalNode": False,
        "LocalNode": "local-package",
    }


def test_cache_context_fingerprints_runtime_effective_consensus_projection():
    pyproject = _pyproject()
    pyproject.nodes.get_existing.return_value = {
        "comfyui-deforum": NodeInfo(
            name="ComfyUI-Deforum",
            registry_id="comfyui-deforum",
            version="dev",
            source="development",
        )
    }
    pyproject.workflows.get_all_with_resolutions.return_value = {
        "existing": {"custom_node_map": {"DeforumGetNode": "ComfyUI-Deforum"}},
        "new": {"nodes": []},
    }
    dependencies = WorkflowDependencies(
        workflow_name="new",
        non_builtin_nodes=[WorkflowNode(id="1", type="DeforumGetNode")],
    )

    builder = WorkflowResolutionContextBuilder(
        pyproject=pyproject,
        model_repository=Mock(),
        cec_path=None,
        builtin_versions_repository=None,
        normalize_package_id=lambda package_id: package_id.lower(),
    )

    context = builder.build_cache_fingerprint_context(
        dependencies,
        resolution_state_hash="state",
        models_sync_time="sync",
    )

    assert context["consensus_custom_mappings"] == {
        "DeforumGetNode": "comfyui-deforum",
    }
    assert context["consensus_declared_packages"] == {
        "comfyui-deforum": {
            "name": "ComfyUI-Deforum",
            "registry_id": "comfyui-deforum",
            "version": "dev",
            "repository": None,
            "source": "development",
        }
    }


def test_cache_context_declared_packages_stays_workflow_scoped():
    pyproject = _pyproject()
    pyproject.workflows.get_all_with_resolutions.return_value = {
        "workflow_a": {"nodes": ["pkg-a"], "custom_node_map": {}}
    }
    pyproject.nodes.get_existing.return_value = {
        "pkg-a": NodeInfo(name="Package A", version="1.0.0", source="registry"),
        "pkg-b": NodeInfo(name="Package B", version="2.0.0", source="registry"),
    }
    dependencies = WorkflowDependencies(workflow_name="workflow_a")

    builder = WorkflowResolutionContextBuilder(
        pyproject=pyproject,
        model_repository=Mock(),
        cec_path=None,
        builtin_versions_repository=None,
    )

    context = builder.build_cache_fingerprint_context(
        dependencies,
        resolution_state_hash="state",
        models_sync_time="sync",
    )

    assert context["declared_packages"] == {
        "pkg-a": {
            "version": "1.0.0",
            "repository": None,
            "source": "registry",
        }
    }


def test_cache_context_can_use_explicit_workflow_name_for_existing_cache_api():
    pyproject = _pyproject()
    pyproject.workflows.get_all_with_resolutions.return_value = {
        "stored_name": {"nodes": ["pkg-a"], "custom_node_map": {}},
        "dependency_name": {"nodes": ["pkg-b"], "custom_node_map": {}},
    }
    pyproject.nodes.get_existing.return_value = {
        "pkg-a": NodeInfo(name="Package A", version="1.0.0", source="registry"),
        "pkg-b": NodeInfo(name="Package B", version="2.0.0", source="registry"),
    }
    dependencies = WorkflowDependencies(workflow_name="dependency_name")

    builder = WorkflowResolutionContextBuilder(
        pyproject=pyproject,
        model_repository=Mock(),
        cec_path=None,
        builtin_versions_repository=None,
    )

    context = builder.build_cache_fingerprint_context(
        dependencies,
        workflow_name="stored_name",
        resolution_state_hash="state",
        models_sync_time="sync",
    )

    declared_packages = context["declared_packages"]
    assert isinstance(declared_packages, dict)
    assert set(declared_packages) == {"pkg-a"}


def test_runtime_context_includes_previous_and_global_model_resolution_state():
    pyproject = _pyproject()
    ref = WorkflowNodeWidgetRef(
        node_id="12",
        node_type="CheckpointLoaderSimple",
        widget_index=0,
        widget_value="model.safetensors",
    )
    workflow_model = ManifestWorkflowModel(
        filename="model.safetensors",
        category="checkpoints",
        criticality="required",
        status="resolved",
        nodes=[ref],
        hash="abc123",
    )
    global_model = ManifestModel(
        hash="abc123",
        filename="model.safetensors",
        size=123,
        relative_path="checkpoints/model.safetensors",
        category="checkpoints",
    )
    pyproject.workflows.get_workflow_models.return_value = [workflow_model]
    pyproject.models.get_all.return_value = [global_model]

    builder = WorkflowResolutionContextBuilder(
        pyproject=pyproject,
        model_repository=Mock(),
        cec_path=None,
        builtin_versions_repository=None,
    )

    context = builder.build_runtime_context(
        WorkflowDependencies(workflow_name="workflow_a"),
        auto_select_ambiguous=False,
    )

    assert context.previous_model_resolutions == {ref: workflow_model}
    assert context.global_models == {"abc123": global_model}
    assert context.auto_select_ambiguous is False


def test_cache_context_includes_model_index_subset_for_found_model_filenames():
    pyproject = _pyproject()
    pyproject.workflows.get_all_with_resolutions.return_value = {
        "workflow_a": {"nodes": [], "custom_node_map": {}}
    }
    model_repository = Mock()
    model_repository.find_by_filename.return_value = [
        SimpleNamespace(
            hash="abc123",
            relative_path="checkpoints/model.safetensors",
            category="checkpoints",
        )
    ]
    dependencies = WorkflowDependencies(
        workflow_name="workflow_a",
        found_models=[
            WorkflowNodeWidgetRef(
                node_id="12",
                node_type="CheckpointLoaderSimple",
                widget_index=0,
                widget_value="nested/model.safetensors",
            )
        ],
    )

    builder = WorkflowResolutionContextBuilder(
        pyproject=pyproject,
        model_repository=model_repository,
        cec_path=None,
        builtin_versions_repository=None,
    )

    context = builder.build_cache_fingerprint_context(
        dependencies,
        resolution_state_hash="state",
        models_sync_time="sync",
    )

    assert context["model_index_subset"] == {
        "model.safetensors": [
            {
                "hash": "abc123",
                "relative_path": "checkpoints/model.safetensors",
                "category": "checkpoints",
            }
        ]
    }
