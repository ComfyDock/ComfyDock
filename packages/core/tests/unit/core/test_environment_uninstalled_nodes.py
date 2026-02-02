"""Unit tests for Environment.get_uninstalled_nodes() method.

Tests the correct behavior:
- get_uninstalled_nodes() should check workflow node references in pyproject.toml
- Compare against installed nodes in [tool.comfygit.nodes]
- Return node IDs that are referenced in workflows but not installed
"""

from unittest.mock import Mock

from comfygit_core.models.shared import NodeInfo


class TestGetUninstalledNodes:
    """Unit tests for get_uninstalled_nodes() logic."""

    def test_returns_workflow_nodes_not_installed(self):
        """Should return nodes referenced in workflows but not installed."""
        # ARRANGE: Mock environment
        from comfygit_core.core.environment import Environment

        env = Mock(spec=Environment)
        env.pyproject = Mock()

        # Mock: Workflow references 3 nodes
        env.pyproject.workflows.get_all_with_resolutions.return_value = {
            "workflow1": {
                "nodes": ["node-a", "node-b", "node-c"]
            }
        }

        # Mock: Only node-a is installed
        env.pyproject.nodes.get_existing.return_value = {
            "node-a": NodeInfo(name="node-a", registry_id="node-a", source="registry")
        }

        # Bind the actual method
        env.get_uninstalled_nodes = Environment.get_uninstalled_nodes.__get__(env, Environment)

        # ACT
        uninstalled = env.get_uninstalled_nodes()

        # ASSERT
        assert len(uninstalled) == 2, f"Should find 2 uninstalled nodes. Got: {uninstalled}"
        assert "node-b" in uninstalled, "Should include node-b"
        assert "node-c" in uninstalled, "Should include node-c"
        assert "node-a" not in uninstalled, "Should NOT include installed node-a"

    def test_returns_empty_when_all_installed(self):
        """Should return empty list when all workflow nodes are installed."""
        # ARRANGE
        from comfygit_core.core.environment import Environment

        env = Mock(spec=Environment)
        env.pyproject = Mock()

        # Mock: Workflow references 2 nodes
        env.pyproject.workflows.get_all_with_resolutions.return_value = {
            "workflow1": {
                "nodes": ["node-a", "node-b"]
            }
        }

        # Mock: Both nodes are installed
        env.pyproject.nodes.get_existing.return_value = {
            "node-a": NodeInfo(name="node-a", registry_id="node-a", source="registry"),
            "node-b": NodeInfo(name="node-b", registry_id="node-b", source="registry")
        }

        env.get_uninstalled_nodes = Environment.get_uninstalled_nodes.__get__(env, Environment)

        # ACT
        uninstalled = env.get_uninstalled_nodes()

        # ASSERT
        assert len(uninstalled) == 0, f"Should return empty when all installed. Got: {uninstalled}"

    def test_handles_multiple_workflows(self):
        """Should aggregate nodes from all workflows."""
        # ARRANGE
        from comfygit_core.core.environment import Environment

        env = Mock(spec=Environment)
        env.pyproject = Mock()

        # Mock: Multiple workflows with different nodes
        env.pyproject.workflows.get_all_with_resolutions.return_value = {
            "workflow1": {
                "nodes": ["node-a", "node-b"]
            },
            "workflow2": {
                "nodes": ["node-b", "node-c"]  # node-b overlaps
            }
        }

        # Mock: Only node-a is installed
        env.pyproject.nodes.get_existing.return_value = {
            "node-a": NodeInfo(name="node-a", registry_id="node-a", source="registry")
        }

        env.get_uninstalled_nodes = Environment.get_uninstalled_nodes.__get__(env, Environment)

        # ACT
        uninstalled = env.get_uninstalled_nodes()

        # ASSERT
        assert len(uninstalled) == 2, f"Should find 2 unique uninstalled nodes. Got: {uninstalled}"
        assert "node-b" in uninstalled
        assert "node-c" in uninstalled

    def test_returns_empty_when_no_workflows(self):
        """Should return empty list when no workflows exist."""
        # ARRANGE
        from comfygit_core.core.environment import Environment

        env = Mock(spec=Environment)
        env.pyproject = Mock()

        # Mock: No workflows
        env.pyproject.workflows.get_all_with_resolutions.return_value = {}
        env.pyproject.nodes.get_existing.return_value = {}

        env.get_uninstalled_nodes = Environment.get_uninstalled_nodes.__get__(env, Environment)

        # ACT
        uninstalled = env.get_uninstalled_nodes()

        # ASSERT
        assert len(uninstalled) == 0, "Should return empty when no workflows exist"
