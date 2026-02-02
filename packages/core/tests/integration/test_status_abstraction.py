"""Test that status provides proper abstraction - no pyproject.load() in display layer.

This test validates that WorkflowAnalysisStatus contains all information needed
for display without requiring the CLI to access raw pyproject.toml data.

Abstraction Violation:
- CLI should NOT call env.pyproject.load() to compute display values
- CLI should NOT parse TOML structure with .get('tool', {}).get('comfygit', {})
- CLI should receive complete, ready-to-display data from core

Correct Abstraction:
- uninstalled_nodes: packages that resolved but aren't installed
- nodes_unresolved: nodes that couldn't be resolved to any package
- CLI only iterates and prints - NO business logic
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import simulate_comfyui_save_workflow


class TestStatusAbstraction:
    """Test that status data models provide complete abstraction for display."""

    def test_workflow_analysis_status_tracks_unresolved_nodes(self, test_env):
        """
        WorkflowAnalysisStatus should track nodes that couldn't be resolved.

        Nodes that can't be mapped to a package go to nodes_unresolved.
        """
        # ARRANGE: Create workflow with fake node types (won't resolve)
        workflow_data = {
            "nodes": [
                {"id": "1", "type": "FakeCustomNode1", "widgets_values": []},
                {"id": "2", "type": "FakeCustomNode2", "widgets_values": []}
            ],
            "links": []
        }
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow_data)

        # ACT: Get workflow status
        workflow_status = test_env.workflow_manager.get_workflow_status()

        # ASSERT: WorkflowAnalysisStatus should provide all display info
        test_workflow = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "test_workflow"),
            None
        )

        assert test_workflow is not None, "Workflow should be analyzed"

        # These fake nodes can't be resolved, so they go to nodes_unresolved
        assert len(test_workflow.resolution.nodes_unresolved) == 2, \
            f"Expected 2 unresolved nodes, got {len(test_workflow.resolution.nodes_unresolved)}"

        # uninstalled_nodes only contains resolved-but-not-installed packages
        assert hasattr(test_workflow, 'uninstalled_nodes')
        assert hasattr(test_workflow, 'uninstalled_count')

    def test_cli_display_without_pyproject_access(self, test_env):
        """
        Verify CLI can build complete status display using ONLY model properties.

        This simulates what the CLI _print_workflow_issues() method should do:
        access only WorkflowAnalysisStatus properties, no pyproject.load().
        """
        # ARRANGE: Create workflow with unresolvable node
        workflow_data = {
            "nodes": [{"id": "1", "type": "UnknownNodeType", "widgets_values": []}],
            "links": []
        }
        simulate_comfyui_save_workflow(test_env, "my_workflow", workflow_data)

        # ACT: Get status
        workflow_status = test_env.workflow_manager.get_workflow_status()
        wf = next(
            (w for w in workflow_status.analyzed_workflows if w.name == "my_workflow"),
            None
        )

        # SIMULATE CLI DISPLAY: Should work with ONLY model access
        parts = []

        # Access model property for resolved-but-uninstalled packages
        if wf.uninstalled_count > 0:
            parts.append(f"{wf.uninstalled_count} packages needed for installation")

        # Access resolution property for unresolvable nodes
        if wf.resolution.nodes_unresolved:
            parts.append(f"{len(wf.resolution.nodes_unresolved)} nodes couldn't be resolved")

        if wf.resolution.models_unresolved:
            parts.append(f"{len(wf.resolution.models_unresolved)} models not found")

        if wf.resolution.models_ambiguous:
            parts.append(f"{len(wf.resolution.models_ambiguous)} ambiguous models")

        # VERIFY: Display parts were created successfully
        assert len(parts) > 0, "Should have generated display parts"
        # The unknown node can't be resolved, so it appears as unresolved
        assert "1 nodes couldn't be resolved" in parts[0], \
            f"Expected unresolved message, got: {parts[0]}"

    def test_multiple_workflows_with_unresolved_nodes(self, test_env):
        """Test abstraction works correctly with multiple workflows."""
        # ARRANGE: Create 2 workflows with different unresolvable nodes
        for _i, (name, node_count) in enumerate([
            ("workflow_a", 1),  # 1 unresolvable node
            ("workflow_b", 3)   # 3 unresolvable nodes
        ]):
            workflow_data = {
                "nodes": [
                    {"id": str(j), "type": f"UnknownNode{name}_{j}", "widgets_values": []}
                    for j in range(node_count)
                ],
                "links": []
            }
            simulate_comfyui_save_workflow(test_env, name, workflow_data)

        # ACT: Get status
        workflow_status = test_env.workflow_manager.get_workflow_status()

        # ASSERT: Each workflow should have correct unresolved count
        workflow_a = next((w for w in workflow_status.analyzed_workflows if w.name == "workflow_a"), None)
        workflow_b = next((w for w in workflow_status.analyzed_workflows if w.name == "workflow_b"), None)

        assert workflow_a is not None and workflow_b is not None

        # Check unresolved nodes (nodes that couldn't be mapped to packages)
        assert len(workflow_a.resolution.nodes_unresolved) == 1, \
            f"workflow_a should have 1 unresolved, got {len(workflow_a.resolution.nodes_unresolved)}"
        assert len(workflow_b.resolution.nodes_unresolved) == 3, \
            f"workflow_b should have 3 unresolved, got {len(workflow_b.resolution.nodes_unresolved)}"
