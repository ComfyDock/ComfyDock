"""Integration tests for workflow resolution with node installation.

Tests the full flow:
1. Resolve workflow dependencies (updates pyproject.toml)
2. Detect uninstalled nodes
3. Install missing nodes to filesystem
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import simulate_comfyui_save_workflow


class TestWorkflowResolveInstall:
    """Test workflow resolution triggers node installation."""

    def test_get_uninstalled_nodes_returns_missing_after_resolve(self, test_env):
        """After resolving workflow, get_uninstalled_nodes() should return nodes not installed."""
        # ARRANGE: Create workflow with missing custom nodes
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
                    "properties": {},
                    "widgets_values": []
                }
            ],
            "links": [[1, 1, 0, 2, 0, "IMAGE"]],
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4
        }

        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow_data)

        # ACT: Simulate workflow resolution adding node to workflow section
        config = test_env.pyproject.load()
        if "tool" not in config:
            config["tool"] = {}
        if "comfygit" not in config["tool"]:
            config["tool"]["comfygit"] = {}
        if "workflows" not in config["tool"]["comfygit"]:
            config["tool"]["comfygit"]["workflows"] = {}

        # Add workflow with node reference (this is what resolve_workflow does)
        config["tool"]["comfygit"]["workflows"]["test_workflow"] = {
            "path": "workflows/test_workflow.json",
            "nodes": ["rgthree-comfy"]  # Node is referenced but NOT installed
        }
        test_env.pyproject.save(config)

        # ASSERT: Node should be in workflow but not installed
        uninstalled = test_env.get_uninstalled_nodes()

        assert len(uninstalled) == 1, \
            f"Should find 1 uninstalled node. Found: {uninstalled}"
        assert "rgthree-comfy" in uninstalled, \
            f"Should identify rgthree-comfy as uninstalled. Found: {uninstalled}"

    def test_get_uninstalled_nodes_returns_empty_when_installed(self, test_env):
        """After nodes are installed, get_uninstalled_nodes() should return empty."""
        # ARRANGE: Add node to workflow AND to installed nodes
        config = test_env.pyproject.load()
        if "tool" not in config:
            config["tool"] = {}
        if "comfygit" not in config["tool"]:
            config["tool"]["comfygit"] = {}

        # Add workflow with node reference
        if "workflows" not in config["tool"]["comfygit"]:
            config["tool"]["comfygit"]["workflows"] = {}
        config["tool"]["comfygit"]["workflows"]["test_workflow"] = {
            "path": "workflows/test_workflow.json",
            "nodes": ["rgthree-comfy"]
        }

        # Add to installed nodes
        if "nodes" not in config["tool"]["comfygit"]:
            config["tool"]["comfygit"]["nodes"] = {}
        config["tool"]["comfygit"]["nodes"]["rgthree-comfy"] = {
            "name": "rgthree-comfy",
            "registry_id": "rgthree-comfy",
            "source": "registry",
            "version": "1.0.0"
        }
        test_env.pyproject.save(config)

        # ACT
        uninstalled = test_env.get_uninstalled_nodes()

        # ASSERT: Should be empty since node is installed
        assert len(uninstalled) == 0, \
            f"Should find 0 uninstalled nodes when node is in [tool.comfygit.nodes]. Found: {uninstalled}"

    def test_get_uninstalled_nodes_handles_multiple_nodes(self, test_env):
        """Should correctly identify multiple missing nodes."""
        # ARRANGE: Add workflow with 2 nodes, only install 1
        config = test_env.pyproject.load()
        if "tool" not in config:
            config["tool"] = {}
        if "comfygit" not in config["tool"]:
            config["tool"]["comfygit"] = {}

        # Add workflow with two node references
        if "workflows" not in config["tool"]["comfygit"]:
            config["tool"]["comfygit"]["workflows"] = {}
        config["tool"]["comfygit"]["workflows"]["test_workflow"] = {
            "path": "workflows/test_workflow.json",
            "nodes": ["rgthree-comfy", "comfyui-manager"]
        }

        # Install only one node
        if "nodes" not in config["tool"]["comfygit"]:
            config["tool"]["comfygit"]["nodes"] = {}
        config["tool"]["comfygit"]["nodes"]["rgthree-comfy"] = {
            "name": "rgthree-comfy",
            "registry_id": "rgthree-comfy",
            "source": "registry",
            "version": "1.0.0"
        }
        test_env.pyproject.save(config)

        # ACT
        uninstalled = test_env.get_uninstalled_nodes()

        # ASSERT: Should find only the missing node (comfyui-manager)
        assert len(uninstalled) == 1, \
            f"Should find 1 uninstalled node. Found: {uninstalled}"
        assert "comfyui-manager" in uninstalled, \
            f"Should identify comfyui-manager as uninstalled. Found: {uninstalled}"
