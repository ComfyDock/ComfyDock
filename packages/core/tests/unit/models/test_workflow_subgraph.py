"""Unit tests for Workflow dataclass subgraph support."""
from comfygit_core.models.workflow import Workflow


class TestWorkflowSubgraphParsing:
    """Test parsing workflows with subgraphs."""

    def test_parse_workflow_with_single_subgraph(self):
        """Parse workflow with one subgraph containing builtin nodes."""
        workflow_json = {
            "id": "test-id",
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
                    "widgets_values": ["ComfyUI"]
                },
                {
                    "id": 10,
                    "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",  # Subgraph UUID
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
                                "flags": {},
                                "order": 1,
                                "mode": 0,
                                "inputs": [],
                                "outputs": [],
                                "properties": {},
                                "widgets_values": ["v1-5-pruned-emaonly-fp16.safetensors"]
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
        workflow = Workflow.from_json(workflow_json)

        # ASSERT: Should parse 3 real nodes (SaveImage + 2 nodes from subgraph)
        # Should skip the UUID node (subgraph reference)
        assert len(workflow.nodes) == 3, \
            f"Expected 3 real nodes, got {len(workflow.nodes)}: {list(workflow.nodes.keys())}"

        # Check node types extracted
        node_types = {node.type for node in workflow.nodes.values()}
        assert "SaveImage" in node_types
        assert "KSampler" in node_types
        assert "CheckpointLoaderSimple" in node_types
        assert "0a58ac1f-cb15-4e01-aab3-26292addb965" not in node_types, \
            "UUID subgraph reference should be filtered out"

    def test_parse_workflow_with_nested_subgraphs(self):
        """Parse workflow with nested subgraphs (subgraph within subgraph)."""
        workflow_json = {
            "id": "test-nested",
            "revision": 0,
            "last_node_id": 11,
            "last_link_id": 10,
            "nodes": [
                {
                    "id": 9,
                    "type": "SaveImage",
                    "pos": [1142, 191],
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["ComfyUI"]
                },
                {
                    "id": 10,
                    "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",  # Text2Img subgraph
                    "pos": [637, 187],
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
                                "id": 10,
                                "type": "CheckpointLoaderSimple",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["model.safetensors"]
                            },
                            {
                                "id": 11,
                                "type": "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa",  # Prompts subgraph
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
                                "widgets_values": ["positive prompt"]
                            },
                            {
                                "id": 7,
                                "type": "CLIPTextEncode",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["negative prompt"]
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
        workflow = Workflow.from_json(workflow_json)

        # ASSERT: Should parse 5 real nodes:
        # - SaveImage (top-level)
        # - KSampler, CheckpointLoaderSimple (from Text2Img subgraph)
        # - CLIPTextEncode x2 (from prompts subgraph)
        # Should skip 2 UUID nodes (subgraph references)
        assert len(workflow.nodes) == 5, \
            f"Expected 5 real nodes, got {len(workflow.nodes)}: {list(workflow.nodes.keys())}"

        node_types = {node.type for node in workflow.nodes.values()}
        assert "SaveImage" in node_types
        assert "KSampler" in node_types
        assert "CheckpointLoaderSimple" in node_types
        assert "CLIPTextEncode" in node_types

        # Verify UUID references are filtered
        assert "0a58ac1f-cb15-4e01-aab3-26292addb965" not in node_types
        assert "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa" not in node_types

    def test_parse_workflow_without_subgraphs(self):
        """Parse standard workflow without any subgraphs (baseline behavior)."""
        workflow_json = {
            "id": "standard",
            "revision": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "CheckpointLoaderSimple",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["model.safetensors"]
                },
                {
                    "id": 2,
                    "type": "KSampler",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": []
                }
            ],
            "links": [],
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4
        }

        # ACT
        workflow = Workflow.from_json(workflow_json)

        # ASSERT
        assert len(workflow.nodes) == 2
        node_types = {node.type for node in workflow.nodes.values()}
        assert "CheckpointLoaderSimple" in node_types
        assert "KSampler" in node_types

    def test_subgraph_node_id_collision_handling(self):
        """Test that node IDs are properly scoped when same ID exists in different subgraphs."""
        workflow_json = {
            "id": "collision-test",
            "revision": 0,
            "nodes": [
                {
                    "id": 10,
                    "type": "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa",
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
                        "id": "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa",
                        "name": "subgraph1",
                        "nodes": [
                            {
                                "id": 10,  # Same ID as top-level node
                                "type": "CheckpointLoaderSimple",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["model1.safetensors"]
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
        workflow = Workflow.from_json(workflow_json)

        # ASSERT: Should have only 1 real node (the CheckpointLoader from subgraph)
        # Top-level node 10 is a subgraph reference (UUID), so should be filtered
        assert len(workflow.nodes) == 1

        # The one real node should be the CheckpointLoader
        real_node = list(workflow.nodes.values())[0]
        assert real_node.type == "CheckpointLoaderSimple"
        assert real_node.widgets_values[0] == "model1.safetensors"

    def test_node_types_property_with_subgraphs(self):
        """Test that node_types property returns unique real node types."""
        workflow_json = {
            "id": "types-test",
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
                                "id": 2,
                                "type": "KSampler",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": []
                            },
                            {
                                "id": 3,
                                "type": "KSampler",  # Duplicate type
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

        # ACT
        workflow = Workflow.from_json(workflow_json)

        # ASSERT
        node_types = workflow.node_types
        assert len(node_types) == 2, "Should have 2 unique types"
        assert "KSampler" in node_types
        assert "CheckpointLoaderSimple" in node_types
        assert "0a58ac1f-cb15-4e01-aab3-26292addb965" not in node_types

    def test_empty_subgraphs_handled_gracefully(self):
        """Test workflow with empty subgraphs section."""
        workflow_json = {
            "id": "empty",
            "revision": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "SaveImage",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": []
                }
            ],
            "links": [],
            "definitions": {
                "subgraphs": []
            },
            "config": {},
            "version": 0.4
        }

        # ACT
        workflow = Workflow.from_json(workflow_json)

        # ASSERT
        assert len(workflow.nodes) == 1
        assert list(workflow.nodes.values())[0].type == "SaveImage"


class TestWorkflowSubgraphSerialization:
    """Test serializing workflows with subgraphs (round-trip)."""

    def test_roundtrip_preserves_all_subgraph_fields(self):
        """Test that from_json → to_json preserves ALL subgraph fields for ComfyUI schema compliance."""
        # ARRANGE: Full subgraph structure with all required fields
        original_json = {
            "id": "2d79c89b-97d2-47cb-b45c-c99889bc5c5d",
            "revision": 0,
            "last_node_id": 11,
            "last_link_id": 10,
            "nodes": [
                {
                    "id": 9,
                    "type": "SaveImage",
                    "pos": [1142.4, 191.7],
                    "size": [210, 270],
                    "flags": {},
                    "order": 1,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [],
                    "properties": {},
                    "widgets_values": ["ComfyUI"]
                },
                {
                    "id": 10,
                    "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",
                    "pos": [585.6, 191.3],
                    "size": [467.7, 438],
                    "flags": {},
                    "order": 0,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [
                        {"name": "IMAGE", "type": "IMAGE", "links": [10]}
                    ],
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
                        "version": 1,
                        "state": {
                            "lastGroupId": 0,
                            "lastNodeId": 12,
                            "lastLinkId": 28,
                            "lastRerouteId": 0
                        },
                        "revision": 0,
                        "config": {},
                        "name": "Text2Img",
                        "inputNode": {
                            "id": -10,
                            "bounding": [-154, 415.5, 120, 40]
                        },
                        "outputNode": {
                            "id": -20,
                            "bounding": [1479, 405.5, 120, 80]
                        },
                        "inputs": [],
                        "outputs": [
                            {
                                "id": "90b2e3c7-4eb3-438e-a39a-45813c6d8ed4",
                                "name": "IMAGE",
                                "type": "IMAGE",
                                "linkIds": [9],
                                "pos": [1499, 425.5]
                            }
                        ],
                        "widgets": [],
                        "nodes": [
                            {
                                "id": 3,
                                "type": "KSampler",
                                "pos": [850, 200],
                                "size": [315, 262],
                                "flags": {},
                                "order": 4,
                                "mode": 0,
                                "inputs": [],
                                "outputs": [],
                                "properties": {},
                                "widgets_values": [123, "randomize", 20, 8]
                            },
                            {
                                "id": 10,
                                "type": "CheckpointLoaderSimple",
                                "pos": [44.4, 357.6],
                                "size": [315, 98],
                                "flags": {},
                                "order": 1,
                                "mode": 0,
                                "inputs": [],
                                "outputs": [],
                                "properties": {},
                                "widgets_values": ["v1-5-pruned-emaonly-fp16.safetensors"]
                            }
                        ],
                        "groups": [],
                        "links": [],
                        "extra": {}
                    }
                ]
            },
            "config": {},
            "extra": {},
            "version": 0.4
        }

        # ACT: Parse and serialize back
        workflow = Workflow.from_json(original_json)
        reconstructed_json = workflow.to_json()

        # ASSERT: All subgraph fields must be preserved
        assert "definitions" in reconstructed_json, "definitions should exist"
        assert "subgraphs" in reconstructed_json["definitions"], "subgraphs should exist"

        subgraphs = reconstructed_json["definitions"]["subgraphs"]
        assert len(subgraphs) == 1, "Should have 1 subgraph"

        subgraph = subgraphs[0]

        # Required fields for ComfyUI Zod schema
        assert subgraph["id"] == "0a58ac1f-cb15-4e01-aab3-26292addb965", "id should match"
        assert subgraph["version"] == 1, "version should be 1 (literal)"
        assert subgraph["revision"] == 0, "revision should be preserved"
        assert "state" in subgraph, "state is required"
        assert subgraph["state"]["lastNodeId"] == 12, "state.lastNodeId should be preserved"
        assert "inputNode" in subgraph, "inputNode is required"
        assert subgraph["inputNode"]["id"] == -10, "inputNode.id should be preserved"
        assert "outputNode" in subgraph, "outputNode is required"
        assert subgraph["outputNode"]["id"] == -20, "outputNode.id should be preserved"
        assert "inputs" in subgraph, "inputs array is required"
        assert "outputs" in subgraph, "outputs array is required"
        assert len(subgraph["outputs"]) == 1, "Should have 1 output"
        assert "widgets" in subgraph, "widgets array is required"
        assert "config" in subgraph, "config is required"
        assert "groups" in subgraph, "groups is required"
        assert "extra" in subgraph, "extra is required"

    def test_roundtrip_with_nested_subgraphs(self):
        """Test round-trip with nested subgraphs preserves all structure."""
        original_json = {
            "id": "nested-test",
            "revision": 0,
            "last_node_id": 11,
            "last_link_id": 10,
            "nodes": [
                {
                    "id": 9,
                    "type": "SaveImage",
                    "pos": [1142, 191],
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": []
                },
                {
                    "id": 10,
                    "type": "0a58ac1f-cb15-4e01-aab3-26292addb965",
                    "pos": [585, 191],
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": []
                }
            ],
            "links": [],
            "groups": [],
            "definitions": {
                "subgraphs": [
                    {
                        "id": "0a58ac1f-cb15-4e01-aab3-26292addb965",
                        "version": 1,
                        "state": {"lastNodeId": 12, "lastLinkId": 28},
                        "revision": 0,
                        "config": {},
                        "name": "Text2Img",
                        "inputNode": {"id": -10},
                        "outputNode": {"id": -20},
                        "inputs": [],
                        "outputs": [],
                        "widgets": [],
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
                                "id": 11,
                                "type": "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa",
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
                        "version": 1,
                        "state": {"lastNodeId": 10, "lastLinkId": 20},
                        "revision": 0,
                        "config": {},
                        "name": "prompts",
                        "inputNode": {"id": -10},
                        "outputNode": {"id": -20},
                        "inputs": [],
                        "outputs": [],
                        "widgets": [],
                        "nodes": [
                            {
                                "id": 6,
                                "type": "CLIPTextEncode",
                                "flags": {},
                                "inputs": [],
                                "outputs": [],
                                "widgets_values": ["positive"]
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
        reconstructed_json = workflow.to_json()

        # ASSERT: Both subgraphs preserved with all fields
        subgraphs = reconstructed_json["definitions"]["subgraphs"]
        assert len(subgraphs) == 2, "Should have 2 subgraphs"

        # Find each subgraph by ID
        text2img = next(sg for sg in subgraphs if sg["id"] == "0a58ac1f-cb15-4e01-aab3-26292addb965")
        prompts = next(sg for sg in subgraphs if sg["id"] == "a0ce3421-e264-4b7a-8b6f-e6e20e7fa9aa")

        # Verify required fields on both
        for sg in [text2img, prompts]:
            assert sg["version"] == 1
            assert "state" in sg
            assert "revision" in sg
            assert "inputNode" in sg
            assert "outputNode" in sg
            assert "inputs" in sg
            assert "outputs" in sg
            assert "widgets" in sg

    def test_roundtrip_without_subgraphs_unchanged(self):
        """Test that workflows without subgraphs remain unchanged."""
        original_json = {
            "id": "simple",
            "revision": 0,
            "last_node_id": 2,
            "last_link_id": 1,
            "nodes": [
                {
                    "id": 1,
                    "type": "CheckpointLoaderSimple",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["model.safetensors"]
                }
            ],
            "links": [],
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4
        }

        # ACT
        workflow = Workflow.from_json(original_json)
        reconstructed_json = workflow.to_json()

        # ASSERT: No definitions added
        assert "definitions" not in reconstructed_json or reconstructed_json.get("definitions") is None or len(reconstructed_json.get("definitions", {}).get("subgraphs", [])) == 0
