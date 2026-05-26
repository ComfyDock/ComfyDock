"""Integration tests for context-aware node resolution.

Tests the full workflow lifecycle with properties field, session caching,
and custom mappings.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import simulate_comfyui_save_workflow


class TestWorkflowWithPropertiesField:
    """Test workflows with properties field resolve automatically."""

    def test_properties_field_resolves_end_to_end(self, test_env):
        """Workflow with properties cnr_id should resolve without user input."""
        # ARRANGE: Create workflow with properties
        workflow_data = {
            "nodes": [
                {
                    "id": "1",
                    "type": "LoadImage",
                    "pos": [100, 100],
                    "size": [200, 100],
                    "flags": {},
                    "order": 0,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [1]}],
                    "properties": {},
                    "widgets_values": ["example.png"]
                },
                {
                    "id": "2",
                    "type": "Mute / Bypass Repeater (rgthree)",
                    "pos": [400, 100],
                    "size": [200, 100],
                    "flags": {},
                    "order": 1,
                    "mode": 0,
                    "inputs": [{"name": "IMAGE", "type": "IMAGE", "link": 1}],
                    "outputs": [],
                    "properties": {
                        "Node name for S&R": "Mute / Bypass Repeater (rgthree)",
                        "cnr_id": "rgthree-comfy",
                        "ver": "f754c4765849aa748abb35a1f030a5ed6474a69b"
                    },
                    "widgets_values": []
                }
            ],
            "links": [[1, 1, 0, 2, 0, "IMAGE"]],
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4
        }

        # Add rgthree-comfy to global mappings (mock it exists)
        mappings_path = test_env.workspace_paths.cache / "custom_nodes" / "node_mappings.json"
        with open(mappings_path) as f:
            mappings = json.load(f)

        mappings["packages"]["rgthree-comfy"] = {
            "id": "rgthree-comfy",
            "display_name": "rgthree's ComfyUI Nodes",
            "description": "Various utility nodes",
            "repository": "https://github.com/rgthree/rgthree-comfy",
            "versions": {}
        }

        with open(mappings_path, 'w') as f:
            json.dump(mappings, f)

        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow_data)

        # ACT: Analyze and resolve workflow
        analysis, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow")

        # ASSERT: Should resolve from properties
        assert len(resolution.nodes_resolved) > 0, "Should have resolved nodes"

        rgthree_resolved = [n for n in resolution.nodes_resolved if n.package_id == "rgthree-comfy"]
        assert len(rgthree_resolved) == 1, "Should resolve rgthree-comfy from properties"

        resolved_node = rgthree_resolved[0]
        assert resolved_node.match_type == "properties"
        assert "f754c4765849aa748abb35a1f030a5ed6474a69b" in resolved_node.versions
        assert len(resolution.nodes_unresolved) == 0, "No nodes should be unresolved"

    def test_properties_field_alias_cnr_id_resolves_to_canonical(self, test_env):
        """Legacy cnr_id in workflow properties should resolve through alias metadata."""
        workflow_data = {
            "nodes": [
                {
                    "id": "1",
                    "type": "Mute / Bypass Repeater (rgthree)",
                    "pos": [400, 100],
                    "size": [200, 100],
                    "flags": {},
                    "order": 0,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [],
                    "properties": {
                        "Node name for S&R": "Mute / Bypass Repeater (rgthree)",
                        "cnr_id": "rgthree-comfy-legacy",
                        "ver": "legacy-sha"
                    },
                    "widgets_values": []
                }
            ],
            "links": [],
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4
        }

        mappings_path = test_env.workspace_paths.cache / "custom_nodes" / "node_mappings.json"
        with open(mappings_path) as f:
            mappings = json.load(f)

        mappings["package_aliases"] = {"rgthree-comfy-legacy": "rgthree-comfy"}
        mappings["packages"]["rgthree-comfy"] = {
            "id": "rgthree-comfy",
            "display_name": "rgthree's ComfyUI Nodes",
            "description": "Various utility nodes",
            "repository": "https://github.com/rgthree/rgthree-comfy",
            "versions": {}
        }

        with open(mappings_path, 'w') as f:
            json.dump(mappings, f)

        simulate_comfyui_save_workflow(test_env, "test_workflow_alias", workflow_data)

        analysis, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("test_workflow_alias")

        rgthree_resolved = [n for n in resolution.nodes_resolved if n.package_id == "rgthree-comfy"]
        assert len(rgthree_resolved) == 1
        assert rgthree_resolved[0].match_type == "properties"
        assert len(resolution.nodes_unresolved) == 0


class TestSessionDeduplication:
    """Test session-level deduplication across multiple nodes."""

    def test_duplicate_nodes_resolve_once(self, test_env):
        """Workflow with many duplicate node types should only resolve each type once."""
        # ARRANGE: Create workflow with 15 KSampler nodes (realistic scenario)
        nodes = []
        for i in range(15):
            nodes.append({
                "id": str(i + 1),
                "type": "KSampler",
                "pos": [100 * i, 100],
                "size": [200, 100],
                "flags": {},
                "order": i,
                "mode": 0,
                "inputs": [],
                "outputs": [],
                "properties": {},
                "widgets_values": [i, "fixed", 20, 8.0, "euler", "normal", 1.0]
            })

        # Add 5 LoadImage nodes
        for i in range(5):
            nodes.append({
                "id": str(i + 16),
                "type": "LoadImage",
                "pos": [100 * i, 300],
                "size": [200, 100],
                "flags": {},
                "order": i + 15,
                "mode": 0,
                "inputs": [],
                "outputs": [],
                "properties": {},
                "widgets_values": [f"image{i}.png"]
            })

        workflow_data = {
            "nodes": nodes,
            "links": [],
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4
        }

        simulate_comfyui_save_workflow(test_env, "test_dedup", workflow_data)

        # ACT: Analyze and resolve
        analysis, _ = test_env.workflow_manager.analyze_and_resolve_workflow("test_dedup")

        # Check that we only have 2 unique builtin node types
        assert len(analysis.builtin_nodes) == 20, "Should find 20 total builtin nodes"

        # Verify deduplication by checking unique types
        unique_types = {node.type for node in analysis.builtin_nodes}
        assert len(unique_types) == 2, "Should have only 2 unique node types"
        assert "KSampler" in unique_types
        assert "LoadImage" in unique_types


class TestHeuristicFallback:
    """Test heuristic resolution when properties are missing."""

    def test_heuristic_resolves_without_properties(self, test_env):
        """Older workflow without properties should use heuristics if package installed."""
        # ARRANGE: Create workflow WITHOUT properties field
        workflow_data = {
            "nodes": [
                {
                    "id": "1",
                    "type": "Any Switch (rgthree)",  # Has parenthetical hint
                    "pos": [100, 100],
                    "size": [200, 100],
                    "flags": {},
                    "order": 0,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [],
                    "properties": {},  # Empty properties!
                    "widgets_values": []
                }
            ],
            "links": [],
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4
        }

        # Add package to global mappings and simulate it's installed
        mappings_path = test_env.workspace_paths.cache / "custom_nodes" / "node_mappings.json"
        with open(mappings_path) as f:
            mappings = json.load(f)

        mappings["packages"]["rgthree-comfy"] = {
            "id": "rgthree-comfy",
            "display_name": "rgthree's ComfyUI Nodes",
            "repository": "https://github.com/rgthree/rgthree-comfy",
            "versions": {}
        }

        with open(mappings_path, 'w') as f:
            json.dump(mappings, f)

        # Simulate package is installed (add to pyproject nodes)
        config = test_env.pyproject.load()
        if "tool" not in config:
            config["tool"] = {}
        if "comfygit" not in config["tool"]:
            config["tool"]["comfygit"] = {}
        if "nodes" not in config["tool"]["comfygit"]:
            config["tool"]["comfygit"]["nodes"] = {}

        config["tool"]["comfygit"]["nodes"]["rgthree-comfy"] = {
            "name": "rgthree-comfy",
            "registry_id": "rgthree-comfy",
            "source": "registry"
        }
        test_env.pyproject.save(config)

        simulate_comfyui_save_workflow(test_env, "old_workflow", workflow_data)

        # ACT: Analyze and resolve
        analysis, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("old_workflow")

        # ASSERT: CHANGED - should NOT resolve via heuristic, should be unresolved
        assert len(resolution.nodes_unresolved) > 0, "Should be unresolved (no auto-resolve)"
        assert resolution.nodes_unresolved[0].type == "Any Switch (rgthree)"
