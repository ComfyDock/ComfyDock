"""Integration tests for workflow resolution with subgraphs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from comfygit_core.strategies.auto import AutoModelStrategy, AutoNodeStrategy
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.pyproject_assertions import PyprojectAssertions


class TestWorkflowSubgraphResolution:
    """Test that workflows with subgraphs can be resolved correctly."""

    def test_resolve_workflow_with_single_subgraph(self, test_env, test_workspace):
        """Workflow with subgraph should extract and resolve nodes correctly."""
        # ARRANGE: Create model in index
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="sd15.safetensors",
            relative_path="checkpoints",
            category="checkpoints"
        )
        model_builder.index_all()

        # Create workflow with subgraph containing checkpoint loader
        workflow_json = {
            "id": "test-subgraph",
            "revision": 0,
            "nodes": [
                {
                    "id": 9,
                    "type": "SaveImage",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["output"]
                },
                {
                    "id": 10,
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
                        "name": "Text2Img",
                        "nodes": [
                            {
                                "id": 3,
                                "type": "KSampler",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": [123, "fixed", 20, 8]
                            },
                            {
                                "id": 10,
                                "type": "CheckpointLoaderSimple",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["sd15.safetensors"]
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

        # ASSERT: Model from subgraph should be resolved
        assert len(result.models_resolved) == 1, \
            f"Should resolve 1 model from subgraph, got {len(result.models_resolved)}"

        # Check pyproject.toml
        assertions = PyprojectAssertions(test_env)
        actual_hash = result.models_resolved[0].resolved_model.hash

        (
            assertions
            .has_workflow("subgraph_test")
            .has_model_count(1)
            .has_model_with_hash(actual_hash)
            .has_model_with_filename("sd15.safetensors")
            .has_status("resolved")
        )

    def test_commit_captured_subgraph_workflow_writes_model_manifest(
        self,
        test_env,
        test_workspace,
    ):
        """Commit should reconcile models even after save-time capture.

        Save-time capture copies the workflow into `.cec/workflows` before
        commit, making the workflow file appear synced. Commit still needs to
        persist dependency metadata discovered inside subgraph nodes.
        """
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="ltx-2.3-22b-distilled-fp8.safetensors",
            relative_path="checkpoints",
            category="checkpoints",
        )
        model_builder.index_all()

        subgraph_id = "f9f61b10-b689-4d67-b4fa-0acc1d9b5390"
        workflow_json = {
            "id": "captured-subgraph-test",
            "revision": 0,
            "nodes": [
                {
                    "id": 129,
                    "type": subgraph_id,
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": [],
                }
            ],
            "links": [],
            "definitions": {
                "subgraphs": [
                    {
                        "id": subgraph_id,
                        "name": "First-Last-Frame to Video",
                        "nodes": [
                            {
                                "id": 127,
                                "type": "CheckpointLoaderSimple",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "properties": {
                                    "models": [
                                        {
                                            "name": "ltx-2.3-22b-distilled-fp8.safetensors",
                                            "url": (
                                                "https://huggingface.co/Lightricks/LTX-2.3-fp8/"
                                                "resolve/main/ltx-2.3-22b-distilled-fp8.safetensors"
                                            ),
                                            "directory": "checkpoints",
                                        }
                                    ]
                                },
                                "widgets_values": ["ltx-2.3-22b-distilled-fp8.safetensors"],
                            }
                        ],
                        "links": [],
                    }
                ]
            },
            "config": {},
            "version": 0.4,
        }

        simulate_comfyui_save_workflow(test_env, "captured_subgraph", workflow_json)
        test_env.capture_workflow("captured_subgraph")

        workflow_status = test_env.workflow_manager.get_workflow_status()
        captured = next(
            workflow for workflow in workflow_status.analyzed_workflows
            if workflow.name == "captured_subgraph"
        )
        assert captured.sync_state == "synced"
        assert captured.resolution.models_resolved
        expected_hash = captured.resolution.models_resolved[0].resolved_model.hash

        test_env.execute_commit(
            workflow_status=workflow_status,
            message="Add captured subgraph workflow",
        )

        assertions = PyprojectAssertions(test_env)
        (
            assertions
            .has_workflow("captured_subgraph")
            .has_model_count(1)
            .has_model_with_hash(expected_hash)
            .has_model_with_filename("ltx-2.3-22b-distilled-fp8.safetensors")
            .has_status("resolved")
        )
        (
            assertions
            .has_global_model(expected_hash)
            .has_filename("ltx-2.3-22b-distilled-fp8.safetensors")
        )
        assert not test_env.workflow_manager.resolution_changes_manifest(
            captured.resolution,
            config=test_env.pyproject.load(),
        )

    def test_resolve_workflow_with_nested_subgraphs(self, test_env, test_workspace):
        """Workflow with nested subgraphs should extract all nodes."""
        # ARRANGE: Create model
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="model.safetensors",
            relative_path="checkpoints",
            category="checkpoints"
        )
        model_builder.index_all()

        # Create workflow with nested subgraphs
        workflow_json = {
            "id": "nested-test",
            "revision": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",
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
                        "name": "Text2Img",
                        "nodes": [
                            {
                                "id": 2,
                                "type": "CheckpointLoaderSimple",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["model.safetensors"]
                            },
                            {
                                "id": 3,
                                "type": "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa",  # Nested subgraph
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": []
                            }
                        ],
                        "links": []
                    },
                    {
                        "id": "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa",
                        "name": "prompts",
                        "nodes": [
                            {
                                "id": 4,
                                "type": "CLIPTextEncode",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["positive"]
                            },
                            {
                                "id": 5,
                                "type": "CLIPTextEncode",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["negative"]
                            }
                        ],
                        "links": []
                    }
                ]
            },
            "config": {},
            "version": 0.4
        }

        simulate_comfyui_save_workflow(test_env, "nested_test", workflow_json)

        # ACT: Resolve workflow
        result = test_env.resolve_workflow(
            name="nested_test",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # ASSERT: Model should be resolved from nested structure
        assert len(result.models_resolved) == 1
        assert result.models_resolved[0].resolved_model.filename == "model.safetensors"

    def test_status_shows_workflow_with_subgraphs(self, test_env):
        """Status command should work with subgraph workflows."""
        # ARRANGE: Create workflow with subgraph
        workflow_json = {
            "id": "status-test",
            "revision": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",
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
                        "name": "subgraph",
                        "nodes": [
                            {
                                "id": 2,
                                "type": "KSampler",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": []
                            }
                        ],
                        "links": []
                    }
                ]
            },
            "config": {},
            "version": 0.4
        }

        simulate_comfyui_save_workflow(test_env, "status_test", workflow_json)

        # ACT: Get status
        status = test_env.status()

        # ASSERT: Workflow should be detected
        assert "status_test" in status.workflow.sync_status.new

        # Check detailed status
        workflow_status = next(
            (w for w in status.workflow.analyzed_workflows if w.name == "status_test"),
            None
        )
        assert workflow_status is not None
        assert workflow_status.node_count == 1, \
            "Should count real nodes from subgraph, not UUID references"

    def test_subgraph_uuid_not_treated_as_custom_node(self, test_env):
        """UUID subgraph references should not be treated as unresolved custom nodes."""
        # ARRANGE: Create workflow with only subgraph reference (no real custom nodes)
        workflow_json = {
            "id": "uuid-test",
            "revision": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",  # UUID subgraph
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
                        "name": "test",
                        "nodes": [
                            {
                                "id": 2,
                                "type": "SaveImage",  # Builtin node
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": []
                            }
                        ],
                        "links": []
                    }
                ]
            },
            "config": {},
            "version": 0.4
        }

        simulate_comfyui_save_workflow(test_env, "uuid_test", workflow_json)

        # ACT: Get status
        status = test_env.status()

        # ASSERT: Should have no unresolved nodes
        workflow_status = next(
            (w for w in status.workflow.analyzed_workflows if w.name == "uuid_test"),
            None
        )
        assert workflow_status is not None
        assert len(workflow_status.resolution.nodes_unresolved) == 0, \
            "UUID subgraph reference should not be treated as unresolved node"
        assert len(workflow_status.resolution.nodes_ambiguous) == 0
