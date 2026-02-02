"""Test that CLI status displays disabled nodes.

This tests that the status command shows disabled nodes so users are aware
of nodes they've disabled.
"""

import sys
from pathlib import Path

# Import core test helpers
core_tests_path = Path(__file__).parent.parent.parent / "core" / "tests"
sys.path.insert(0, str(core_tests_path))



class TestStatusDisabledNodesDisplay:
    """Test that CLI status correctly displays disabled nodes."""

    def test_status_shows_disabled_nodes_in_comparison(self, test_env):
        """
        Test that status comparison includes disabled_nodes for CLI display.

        This ensures the EnvironmentComparison has the disabled_nodes data
        that the CLI needs to display the disabled nodes section.
        """
        # ARRANGE: Create disabled node on filesystem
        custom_nodes = test_env.comfyui_path / "custom_nodes"
        custom_nodes.mkdir(parents=True, exist_ok=True)

        disabled_node = custom_nodes / "MyTestNode.disabled"
        disabled_node.mkdir()

        # Add node to manifest
        config = test_env.pyproject.load()

        if 'nodes' not in config['tool']['comfygit']:
            config['tool']['comfygit']['nodes'] = {}

        config['tool']['comfygit']['nodes']['my-test-node'] = {
            'name': 'MyTestNode',
            'version': '1.0.0',
            'source': 'registry',
            'registry_id': 'my-test-node'
        }

        test_env.pyproject.save(config)

        # ACT: Get status
        status = test_env.status()

        # ASSERT: Disabled node should be in comparison.disabled_nodes
        assert hasattr(status.comparison, 'disabled_nodes'), \
            "EnvironmentComparison should have 'disabled_nodes' attribute"
        assert 'MyTestNode' in status.comparison.disabled_nodes, \
            f"Disabled node should be in disabled_nodes, got: {status.comparison.disabled_nodes}"

        # Should NOT be in missing_nodes
        assert 'MyTestNode' not in status.comparison.missing_nodes, \
            f"Disabled node should not be in missing_nodes, got: {status.comparison.missing_nodes}"

    def test_disabled_node_does_not_trigger_repair_warning(self, test_env):
        """
        Test that a disabled node doesn't cause "Environment needs repair" warning.

        When is_synced is calculated, disabled nodes should not count as missing.
        """
        # ARRANGE: Create disabled node
        custom_nodes = test_env.comfyui_path / "custom_nodes"
        custom_nodes.mkdir(parents=True, exist_ok=True)

        disabled_node = custom_nodes / "MyTestNode.disabled"
        disabled_node.mkdir()

        # Add node to manifest
        config = test_env.pyproject.load()

        if 'nodes' not in config['tool']['comfygit']:
            config['tool']['comfygit']['nodes'] = {}

        config['tool']['comfygit']['nodes']['my-test-node'] = {
            'name': 'MyTestNode',
            'version': '1.0.0',
            'source': 'registry'
        }

        test_env.pyproject.save(config)

        # ACT: Get status
        status = test_env.status()

        # ASSERT: comparison.is_synced should be True (no missing nodes)
        # The only "issue" is the disabled node, which is intentional
        assert len(status.comparison.missing_nodes) == 0, \
            f"Should have no missing nodes, got: {status.comparison.missing_nodes}"
