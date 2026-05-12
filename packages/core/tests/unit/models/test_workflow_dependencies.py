"""Unit tests for WorkflowDependencies."""

from comfygit_core.models.workflow import WorkflowDependencies, WorkflowNodeWidgetRef


def test_total_models_counts_found_models_once() -> None:
    """total_models should equal the number of found model references."""
    found_models = [
        WorkflowNodeWidgetRef(
            node_id="1",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="model-a.safetensors",
        ),
        WorkflowNodeWidgetRef(
            node_id="2",
            node_type="VAELoader",
            widget_index=0,
            widget_value="model-b.safetensors",
        ),
        WorkflowNodeWidgetRef(
            node_id="3",
            node_type="CLIPLoader",
            widget_index=0,
            widget_value="model-c.safetensors",
        ),
    ]
    deps = WorkflowDependencies(workflow_name="wf", found_models=found_models)

    assert deps.total_models == len(found_models)
