"""Tests for WorkflowResolutionService."""

from __future__ import annotations

from unittest.mock import Mock

from comfygit_core.models.workflow import (
    ResolvedModel,
    ResolvedNodePackage,
    WorkflowDependencies,
    WorkflowNode,
    WorkflowNodeWidgetRef,
)
from comfygit_core.services.workflow_resolution_service import (
    ResolutionContext,
    WorkflowResolutionService,
)


def test_resolve_standalone_with_empty_context() -> None:
    global_node_resolver = Mock()
    model_resolver = Mock()
    service = WorkflowResolutionService(global_node_resolver, model_resolver)

    node = WorkflowNode(id="1", type="MyCustomNode")
    model_ref = WorkflowNodeWidgetRef(
        node_id="10",
        node_type="CLIPLoader",
        widget_index=0,
        widget_value="clip.safetensors",
    )
    analysis = WorkflowDependencies(
        workflow_name="wf",
        non_builtin_nodes=[node],
        found_models=[model_ref],
    )

    global_node_resolver.resolve_single_node_with_context.return_value = [
        ResolvedNodePackage(
            node_type="MyCustomNode",
            package_id="comfyui-my-custom-node",
            match_type="exact",
        )
    ]
    model_resolver.resolve_model.return_value = [
        ResolvedModel(
            workflow="wf",
            reference=model_ref,
            match_type="download_intent",
            model_source="https://example.com/clip.safetensors",
        )
    ]

    result = service.resolve(analysis, ResolutionContext())

    assert result.workflow_name == "wf"
    assert len(result.nodes_resolved) == 1
    assert result.nodes_resolved[0].package_id == "comfyui-my-custom-node"
    assert len(result.models_resolved) == 1
    assert result.models_resolved[0].model_source == "https://example.com/clip.safetensors"


def test_resolve_standalone_deduplicates_model_refs() -> None:
    global_node_resolver = Mock()
    model_resolver = Mock()
    service = WorkflowResolutionService(global_node_resolver, model_resolver)

    model_ref1 = WorkflowNodeWidgetRef(
        node_id="10",
        node_type="VAELoader",
        widget_index=0,
        widget_value="vae.safetensors",
    )
    model_ref2 = WorkflowNodeWidgetRef(
        node_id="11",
        node_type="VAELoader",
        widget_index=0,
        widget_value="vae.safetensors",
    )
    analysis = WorkflowDependencies(
        workflow_name="wf",
        non_builtin_nodes=[],
        found_models=[model_ref1, model_ref2],
    )

    model_resolver.resolve_model.return_value = None

    result = service.resolve(analysis, ResolutionContext())

    assert len(result.models_unresolved) == 1
    assert result.models_unresolved[0] == model_ref1
    model_resolver.resolve_model.assert_called_once()
