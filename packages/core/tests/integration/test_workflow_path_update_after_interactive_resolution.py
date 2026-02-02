"""Integration test for workflow JSON path updates after interactive resolution.

Tests that model paths are correctly updated in workflow JSON files after
interactive model resolution via fix_resolution().

This test verifies the fix for the bug where:
1. User interactively resolves a model
2. pyproject.toml is updated (progressive write)
3. Workflow JSON should also be updated (batch write at end)
4. Previously failed silently due to node ID mismatch with cached resolution
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from comfygit_core.strategies.auto import AutoModelStrategy, AutoNodeStrategy
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.pyproject_assertions import PyprojectAssertions


class TestWorkflowPathUpdateAfterInteractiveResolution:
    """Test that workflow JSON is updated after interactive model resolution."""

    def test_workflow_json_updated_after_interactive_resolution(self, test_env, test_workspace):
        """After fix_resolution() resolves models, workflow JSON should be updated with paths."""
        # ARRANGE: Create model in index
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="test-model.safetensors",
            relative_path="checkpoints",
            category="checkpoints"
        )
        model_builder.index_all()

        # Create workflow with checkpoint loader
        workflow_json = {
            "id": "test-interactive",
            "revision": 0,
            "last_node_id": 1,
            "last_link_id": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "CheckpointLoaderSimple",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["test-model.safetensors"]
                }
            ],
            "links": [],
            "config": {},
            "version": 0.4
        }

        simulate_comfyui_save_workflow(test_env, "interactive_test", workflow_json)

        # ACT: Resolve workflow with auto-strategy (simulates user selecting model)
        result = test_env.resolve_workflow(
            name="interactive_test",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # ASSERT: Model should be resolved
        assert len(result.models_resolved) == 1, \
            f"Expected 1 resolved model, got {len(result.models_resolved)}"

        # ASSERT: pyproject.toml should be updated (progressive write)
        assertions = PyprojectAssertions(test_env)
        (
            assertions
            .has_workflow("interactive_test")
            .has_model_count(1)
            .has_model_with_filename("test-model.safetensors")
            .has_status("resolved")
        )

        # ASSERT: Workflow JSON should ALSO be updated (batch write at end)
        workflow_path = test_env.comfyui_path / "user/default/workflows/interactive_test.json"
        assert workflow_path.exists(), f"Workflow file not found: {workflow_path}"

        # Load workflow and check that model path was updated
        with open(workflow_path) as f:
            import json
            updated_workflow = json.load(f)

        # The CheckpointLoaderSimple node should have its widget value updated
        checkpoint_node = next(
            (n for n in updated_workflow["nodes"] if n.get("type") == "CheckpointLoaderSimple"),
            None
        )
        assert checkpoint_node is not None, "CheckpointLoaderSimple node not found in workflow"

        # For builtin nodes, ComfyUI expects just the filename (no base directory)
        # because it automatically prepends "checkpoints/"
        expected_path = "test-model.safetensors"  # NOT "checkpoints/test-model.safetensors"
        actual_path = checkpoint_node["widgets_values"][0]

        assert actual_path == expected_path, \
            f"Workflow JSON not updated! Expected '{expected_path}', got '{actual_path}'"

    def test_workflow_json_updated_with_subgraph_nodes(self, test_env, test_workspace):
        """Workflow JSON should be updated even when models are in subgraph nodes."""
        # ARRANGE: Create models in index
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="checkpoint.safetensors",
            relative_path="checkpoints",
            category="checkpoints"
        )
        model_builder.add_model(
            filename="lora.safetensors",
            relative_path="loras",
            category="loras"
        )
        model_builder.index_all()

        # Create workflow with subgraph containing LoraLoader
        workflow_json = {
            "id": "subgraph-test",
            "revision": 0,
            "last_node_id": 2,
            "last_link_id": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "SaveImage",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["output"]
                },
                {
                    "id": 2,
                    "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",  # Subgraph UUID
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": []
                }
            ],
            "links": [],
            "definitions": {
                "subgraphs": [
                    {
                        "id": "0a58ac1f-cb15-4e01-aab3-26292addb965",
                        "name": "LoaderSubgraph",
                        "nodes": [
                            {
                                "id": 10,
                                "type": "CheckpointLoaderSimple",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["checkpoint.safetensors"]
                            },
                            {
                                "id": 11,
                                "type": "LoraLoader",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["lora.safetensors", 1.0, 1.0]
                            }
                        ],
                        "links": []
                    }
                ]
            },
            "config": {},
            "version": 0.4
        }

        simulate_comfyui_save_workflow(test_env, "subgraph_test", workflow_json)

        # ACT: Resolve workflow
        result = test_env.resolve_workflow(
            name="subgraph_test",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # ASSERT: Both models should be resolved
        assert len(result.models_resolved) == 2, \
            f"Expected 2 resolved models, got {len(result.models_resolved)}"

        # ASSERT: Workflow JSON should be updated with both model paths
        workflow_path = test_env.comfyui_path / "user/default/workflows/subgraph_test.json"
        with open(workflow_path) as f:
            import json
            updated_workflow = json.load(f)

        # Check nodes inside subgraph definition
        subgraph = updated_workflow["definitions"]["subgraphs"][0]

        checkpoint_node = next(
            (n for n in subgraph["nodes"] if n.get("type") == "CheckpointLoaderSimple"),
            None
        )
        assert checkpoint_node is not None, "CheckpointLoaderSimple not found in subgraph"
        assert checkpoint_node["widgets_values"][0] == "checkpoint.safetensors", \
            "Checkpoint path not updated in subgraph"

        lora_node = next(
            (n for n in subgraph["nodes"] if n.get("type") == "LoraLoader"),
            None
        )
        assert lora_node is not None, "LoraLoader not found in subgraph"
        assert lora_node["widgets_values"][0] == "lora.safetensors", \
            "Lora path not updated in subgraph"
