"""Unit tests for Workflow round-trip serialization with subgraphs.

Tests that workflows with subgraphs can be loaded, modified, and saved back
while preserving the original ComfyUI structure.
"""
from comfygit_core.models.workflow import Workflow


class TestWorkflowRoundTripSerialization:
    """Test that workflows can be loaded and saved without corruption."""

    def test_roundtrip_workflow_without_subgraphs(self):
        """Standard workflow should roundtrip perfectly (baseline)."""
        # ARRANGE
        original_json = {
            "id": "standard",
            "revision": 0,
            "last_node_id": 2,
            "last_link_id": 1,
            "nodes": [
                {
                    "id": 1,
                    "type": "CheckpointLoaderSimple",
                    "pos": [100, 100],
                    "size": [200, 100],
                    "flags": {},
                    "order": 0,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [],
                    "properties": {},
                    "widgets_values": ["model.safetensors"]
                },
                {
                    "id": 2,
                    "type": "KSampler",
                    "pos": [400, 100],
                    "size": [300, 200],
                    "flags": {},
                    "order": 1,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [],
                    "properties": {},
                    "widgets_values": [123, "fixed", 20, 8.0]
                }
            ],
            "links": [[1, 1, 0, 2, 0, "MODEL"]],
            "groups": [],
            "config": {},
            "extra": {"ds": {"scale": 1.0}},
            "version": 0.4
        }

        # ACT
        workflow = Workflow.from_json(original_json)
        output_json = workflow.to_json()

        # ASSERT: Structure should match (nodes may be reordered, but content identical)
        assert len(output_json["nodes"]) == 2, "Should have 2 nodes"
        assert output_json["id"] == "standard"
        assert output_json["revision"] == 0
        assert "definitions" not in output_json, "Standard workflow has no definitions"

        # Check nodes are present (order doesn't matter)
        node_types = {n["type"] for n in output_json["nodes"]}
        assert "CheckpointLoaderSimple" in node_types
        assert "KSampler" in node_types

    def test_roundtrip_workflow_with_legacy_groups_without_ids(self):
        """Legacy visual groups without IDs should not block workflow parsing."""
        # ARRANGE
        original_json = {
            "id": "legacy-groups",
            "revision": 0,
            "last_node_id": 1,
            "last_link_id": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "Note",
                    "pos": [100, 100],
                    "size": [200, 100],
                    "flags": {},
                    "order": 0,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [],
                    "properties": {},
                    "widgets_values": ["hello"]
                }
            ],
            "links": [],
            "groups": [
                {
                    "title": "Legacy group",
                    "bounding": [90, 90, 250, 160],
                    "color": "#3f789e",
                    "font_size": 24,
                    "flags": {}
                }
            ],
            "config": {},
            "extra": {},
            "version": 0.4
        }

        # ACT
        workflow = Workflow.from_json(original_json)
        output_json = workflow.to_json()

        # ASSERT
        assert len(workflow.groups) == 1
        assert workflow.groups[0].id is None
        assert output_json["groups"][0]["title"] == "Legacy group"
        assert "id" not in output_json["groups"][0]

    def test_roundtrip_workflow_with_single_subgraph_preserves_structure(self):
        """Workflow with subgraph should preserve original structure on save.

        This is the critical test that currently FAILS. We need to ensure:
        1. Top-level nodes list only has real top-level nodes + UUID reference
        2. Subgraph nodes stay inside definitions.subgraphs[].nodes
        3. definitions is at top-level (not buried in extra)
        """
        # ARRANGE
        original_json = {
            "id": "test-subgraph",
            "revision": 0,
            "last_node_id": 10,
            "last_link_id": 10,
            "nodes": [
                {
                    "id": 9,
                    "type": "SaveImage",
                    "pos": [1142, 191],
                    "size": [210, 270],
                    "flags": {},
                    "order": 1,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [],
                    "properties": {},
                    "widgets_values": ["output"]
                },
                {
                    "id": 10,
                    "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",  # UUID subgraph reference
                    "pos": [637, 187],
                    "size": [467, 434],
                    "flags": {},
                    "order": 0,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [10]}],
                    "properties": {},
                    "widgets_values": []
                }
            ],
            "links": [[10, 10, 0, 9, 0, "IMAGE"]],
            "groups": [],
            "definitions": {
                "subgraphs": [
                    {
                        "id": "0a58ac1f-cb15-4e01-aab3-26292addb965",
                        "name": "Text2Img",
                        "nodes": [
                            {
                                "id": 3,
                                "type": "KSampler",
                                "pos": [850, 200],
                                "size": [300, 400],
                                "flags": {},
                                "order": 0,
                                "mode": 0,
                                "inputs": [],
                                "outputs": [],
                                "properties": {},
                                "widgets_values": [123, "fixed", 20, 8]
                            },
                            {
                                "id": 10,
                                "type": "CheckpointLoaderSimple",
                                "pos": [44, 357],
                                "size": [200, 100],
                                "flags": {},
                                "order": 1,
                                "mode": 0,
                                "inputs": [],
                                "outputs": [],
                                "properties": {},
                                "widgets_values": ["sd15.safetensors"]
                            }
                        ],
                        "links": []
                    }
                ]
            },
            "config": {},
            "extra": {"ds": {"scale": 1.0, "offset": [0, 0]}},
            "version": 0.4
        }

        # ACT
        workflow = Workflow.from_json(original_json)
        output_json = workflow.to_json()

        # ASSERT 1: Top-level structure is correct
        assert "definitions" in output_json, "definitions should be at top-level"
        assert "definitions" not in output_json.get("extra", {}), \
            "definitions should NOT be buried in extra"

        # ASSERT 2: Top-level nodes should only have SaveImage + UUID reference
        assert len(output_json["nodes"]) == 2, \
            f"Top-level should have 2 nodes (SaveImage + UUID ref), got {len(output_json['nodes'])}"

        top_level_types = {n["type"] for n in output_json["nodes"]}
        assert "SaveImage" in top_level_types, "SaveImage should be in top-level nodes"
        assert "0a58ac1f-cb15-4e01-aab3-26292addb965" in top_level_types, \
            "UUID subgraph reference should be in top-level nodes"

        # ASSERT 3: Subgraph structure is preserved
        assert "subgraphs" in output_json["definitions"]
        assert len(output_json["definitions"]["subgraphs"]) == 1

        subgraph = output_json["definitions"]["subgraphs"][0]
        assert subgraph["id"] == "0a58ac1f-cb15-4e01-aab3-26292addb965"
        assert subgraph["name"] == "Text2Img"
        assert len(subgraph["nodes"]) == 2, \
            f"Subgraph should have 2 nodes, got {len(subgraph['nodes'])}"

        # ASSERT 4: Subgraph nodes have correct types and original IDs
        subgraph_node_types = {n["type"] for n in subgraph["nodes"]}
        assert "KSampler" in subgraph_node_types
        assert "CheckpointLoaderSimple" in subgraph_node_types

        # Check original node IDs are restored (not scoped IDs)
        subgraph_node_ids = {n["id"] for n in subgraph["nodes"]}
        assert 3 in subgraph_node_ids, "KSampler should have original ID 3"
        assert 10 in subgraph_node_ids, "CheckpointLoader should have original ID 10"

        # ASSERT 5: extra is preserved without definitions
        assert "ds" in output_json["extra"], "extra.ds should be preserved"
        assert output_json["extra"]["ds"]["scale"] == 1.0

    def test_roundtrip_workflow_with_nested_subgraphs(self):
        """Workflow with nested subgraphs should preserve full structure."""
        # ARRANGE
        original_json = {
            "id": "nested",
            "revision": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "SaveImage",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": []
                },
                {
                    "id": 2,
                    "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",  # Text2Img subgraph
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
                                "widgets_values": []
                            },
                            {
                                "id": 4,
                                "type": "CheckpointLoaderSimple",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["model.safetensors"]
                            },
                            {
                                "id": 5,
                                "type": "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa",  # Prompts subgraph ref
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
                                "id": 6,
                                "type": "CLIPTextEncode",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["positive"]
                            },
                            {
                                "id": 7,
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
            "extra": {},
            "version": 0.4
        }

        # ACT
        workflow = Workflow.from_json(original_json)
        output_json = workflow.to_json()

        # ASSERT: Both subgraphs preserved with correct structure
        assert len(output_json["definitions"]["subgraphs"]) == 2

        subgraph_ids = {sg["id"] for sg in output_json["definitions"]["subgraphs"]}
        assert "0a58ac1f-cb15-4e01-aab3-26292addb965" in subgraph_ids
        assert "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa" in subgraph_ids

        # Text2Img subgraph should have 3 nodes (including nested subgraph reference)
        text2img_sg = next(sg for sg in output_json["definitions"]["subgraphs"]
                          if sg["id"] == "0a58ac1f-cb15-4e01-aab3-26292addb965")
        assert len(text2img_sg["nodes"]) == 3

        text2img_types = {n["type"] for n in text2img_sg["nodes"]}
        assert "KSampler" in text2img_types
        assert "CheckpointLoaderSimple" in text2img_types
        assert "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa" in text2img_types  # Nested ref preserved

    def test_roundtrip_preserves_widget_value_updates(self):
        """Widget value updates should persist through round-trip.

        This simulates the workflow_manager updating model paths.
        """
        # ARRANGE
        original_json = {
            "id": "update-test",
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
                        "name": "test",
                        "nodes": [
                            {
                                "id": 10,
                                "type": "CheckpointLoaderSimple",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["old_model.safetensors"]
                            }
                        ],
                        "links": []
                    }
                ]
            },
            "config": {},
            "version": 0.4
        }

        # ACT: Load, update widget value, save
        workflow = Workflow.from_json(original_json)

        # Update node widget value (simulating workflow_manager.update_workflow_model_paths)
        scoped_id = "0a58ac1f-cb15-4e01-aab3-26292addb965:10"
        assert scoped_id in workflow.nodes, f"Node {scoped_id} should exist in flattened nodes"

        workflow.nodes[scoped_id].widgets_values[0] = "new_model.safetensors"

        output_json = workflow.to_json()

        # ASSERT: Updated value should appear in correct location (subgraph node)
        subgraph = output_json["definitions"]["subgraphs"][0]
        checkpoint_node = next(n for n in subgraph["nodes"] if n["type"] == "CheckpointLoaderSimple")

        assert checkpoint_node["widgets_values"][0] == "new_model.safetensors", \
            "Widget value update should persist in subgraph node"
        assert checkpoint_node["id"] == 10, "Node should have original ID (not scoped)"

    def test_roundtrip_handles_node_id_collisions(self):
        """Node ID collisions between top-level and subgraph should be handled."""
        # ARRANGE: Top-level has node 10, subgraph also has node 10
        original_json = {
            "id": "collision",
            "revision": 0,
            "nodes": [
                {
                    "id": 10,
                    "type": "SaveImage",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["top_level"]
                },
                {
                    "id": 11,
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
                        "name": "test",
                        "nodes": [
                            {
                                "id": 10,
                                "type": "CheckpointLoaderSimple",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["subgraph_node"]
                            }
                        ],
                        "links": []
                    }
                ]
            },
            "config": {},
            "version": 0.4
        }

        # ACT
        workflow = Workflow.from_json(original_json)
        output_json = workflow.to_json()

        # ASSERT: Both nodes should exist in output with original IDs
        top_level_node_10 = next(n for n in output_json["nodes"]
                                  if n["type"] == "SaveImage")
        assert top_level_node_10["id"] == 10
        assert top_level_node_10["widgets_values"][0] == "top_level"

        subgraph_node_10 = output_json["definitions"]["subgraphs"][0]["nodes"][0]
        assert subgraph_node_10["id"] == 10
        assert subgraph_node_10["widgets_values"][0] == "subgraph_node"
