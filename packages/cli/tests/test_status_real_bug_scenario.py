"""Test for the REAL bug: nodes that resolve successfully but aren't installed.

This recreates the exact scenario from the user's environment where:
1. Workflow has nodes that CAN be resolved (they're in node_mappings)
2. Resolution succeeds (nodes_resolved has all packages)
3. But only SOME packages are actually installed
4. Status doesn't show the uninstalled ones because has_issues=False

The key difference from other tests: These nodes WILL resolve because they're
in custom mappings, so has_issues will return False even though they're not installed.
"""

import sys
from pathlib import Path

import pytest

# Import core test helpers
core_tests_path = Path(__file__).parent.parent.parent / "core" / "tests"
sys.path.insert(0, str(core_tests_path))
from conftest import simulate_comfyui_save_workflow  # noqa: E402


class TestStatusRealBugScenario:
    """Test the actual bug: resolved but uninstalled nodes."""

    def test_resolved_but_uninstalled_nodes_not_shown(self, test_env):
        """
        Recreate EXACT scenario from user's environment.

        User has:
        - workflow.nodes = 22 packages
        - [tool.comfygit.nodes.*] = 19 packages (3 missing)
        - [tool.comfygit.node_mappings] has mappings for ALL 22
        - When status runs, it re-resolves and finds all 22 via mappings
        - has_issues returns False (all nodes resolved!)
        - But 3 aren't installed!
        """
        # ARRANGE: Create workflow that uses nodes with custom mappings
        workflow_data = {
            "nodes": [
                {"id": "1", "type": "JWIntegerDiv", "widgets_values": []},
                {"id": "2", "type": "SetNode", "widgets_values": []},
                {"id": "3", "type": "GetNode", "widgets_values": []},
            ],
            "links": []
        }
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow_data)

        # Set up pyproject.toml to match user's scenario
        config = test_env.pyproject.load()

        if 'workflows' not in config['tool']['comfygit']:
            config['tool']['comfygit']['workflows'] = {}
        if 'nodes' not in config['tool']['comfygit']:
            config['tool']['comfygit']['nodes'] = {}
        if 'node_mappings' not in config['tool']['comfygit']:
            config['tool']['comfygit']['node_mappings'] = {}

        # Workflow declares it needs 3 packages (from resolution)
        config['tool']['comfygit']['workflows']['test_workflow'] = {
            'path': 'workflows/test_workflow.json',
            'nodes': ['comfyui-various', 'comfyui-kjnodes', 'uninstalled-pack']
        }

        # Node mappings exist for ALL nodes (this is KEY - they'll resolve!)
        config['tool']['comfygit']['node_mappings']['JWIntegerDiv'] = 'comfyui-various'
        config['tool']['comfygit']['SetNode'] = 'comfyui-kjnodes'
        config['tool']['comfygit']['GetNode'] = 'uninstalled-pack'

        # But only 2 packages are actually installed
        config['tool']['comfygit']['nodes']['comfyui-various'] = {
            'name': 'Various ComfyUI Nodes',
            'source': 'git',
            'repository': 'https://github.com/test/comfyui-various'
        }
        config['tool']['comfygit']['nodes']['comfyui-kjnodes'] = {
            'name': 'ComfyUI KJNodes',
            'source': 'git',
            'repository': 'https://github.com/test/comfyui-kjnodes'
        }
        # uninstalled-pack is NOT in [tool.comfygit.nodes.*]

        test_env.pyproject.save(config)

        # Commit so workflow shows as "synced"
        test_env.workflow_manager.copy_all_workflows()
        import subprocess
        subprocess.run(
            ["git", "add", "-A"],
            cwd=test_env.cec_path,
            check=True,
            capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Add workflow"],
            cwd=test_env.cec_path,
            check=True,
            capture_output=True
        )

        # ACT: Get workflow status (this is what `cg status` does)
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_workflow = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "test_workflow"),
            None
        )

        assert test_workflow is not None, "test_workflow should exist"

        # DEBUG: Show what resolution found
        print("\n=== REAL BUG SCENARIO ===")
        print(f"Workflow needs (from pyproject): {config['tool']['comfygit']['workflows']['test_workflow']['nodes']}")
        print(f"Installed packages: {list(test_env.pyproject.nodes.get_existing().keys())}")
        print(f"Nodes resolved: {[n.package_id for n in test_workflow.resolution.nodes_resolved]}")
        print(f"Nodes unresolved: {[n.type for n in test_workflow.resolution.nodes_unresolved]}")
        print(f"has_issues: {test_workflow.has_issues}")
        print("========================\n")

        # VERIFY: Calculate uninstalled packages
        workflow_needs = set(config['tool']['comfygit']['workflows']['test_workflow']['nodes'])
        installed = set(test_env.pyproject.nodes.get_existing().keys())
        uninstalled = workflow_needs - installed

        print(f"Uninstalled packages: {uninstalled}")
        assert len(uninstalled) == 1, f"Should have 1 uninstalled package, got {len(uninstalled)}"

        # THE BUG: has_issues will be False because all nodes resolved via custom mappings
        # But we have 1 uninstalled package!
        if not test_workflow.has_issues and len(uninstalled) > 0:
            pytest.fail(
                f"BUG CONFIRMED: Workflow has {len(uninstalled)} uninstalled packages "
                f"({uninstalled}) but has_issues={test_workflow.has_issues}. "
                f"The CLI status command won't flag this workflow as having issues!"
            )
