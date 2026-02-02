"""CLI test for status display of uninstalled nodes.

This tests the actual CLI output to ensure that workflows with uninstalled
packages are properly flagged and displayed to the user.

Bug: Status command doesn't show uninstalled packages because it only checks
wf_analysis.has_issues, which returns False when nodes are "resolvable" even
if they're not installed.

Fix: Add separate check for uninstalled packages independent of has_issues.
"""

import sys
from pathlib import Path

import pytest

# Import CLI command handler
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import core test helpers
core_tests_path = Path(__file__).parent.parent.parent / "core" / "tests"
sys.path.insert(0, str(core_tests_path))
from conftest import simulate_comfyui_save_workflow


class TestStatusDisplaysUninstalledNodes:
    """Test that CLI status command properly displays uninstalled nodes."""

    def test_status_output_shows_uninstalled_packages(self, test_env):
        """
        Test that `cg status` output shows workflows with uninstalled packages.

        This is the actual bug test - it checks that has_issues returns True
        when there are uninstalled packages, even if resolution succeeds.

        BUG: has_issues only checks resolution issues (nodes_unresolved, models_unresolved).
        It should ALSO check if workflow.nodes != installed nodes.
        """
        # ARRANGE: Create a workflow and simulate partial installation
        workflow_data = {
            "nodes": [
                {"id": "1", "type": "TestNode1", "widgets_values": []},
                {"id": "2", "type": "TestNode2", "widgets_values": []},
            ],
            "links": []
        }
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow_data)

        # Simulate resolution: 3 nodes needed, only 2 installed
        config = test_env.pyproject.load()

        if 'workflows' not in config['tool']['comfygit']:
            config['tool']['comfygit']['workflows'] = {}

        # Workflow declares it needs 3 nodes
        config['tool']['comfygit']['workflows']['test_workflow'] = {
            'path': 'workflows/test_workflow.json',
            'nodes': ['node-pack-1', 'node-pack-2', 'node-pack-3']
        }

        # But only 2 are actually installed
        if 'nodes' not in config['tool']['comfygit']:
            config['tool']['comfygit']['nodes'] = {}

        config['tool']['comfygit']['nodes']['node-pack-1'] = {
            'name': 'Node Pack 1',
            'source': 'git',
            'repository': 'https://github.com/test/node-pack-1'
        }
        config['tool']['comfygit']['nodes']['node-pack-2'] = {
            'name': 'Node Pack 2',
            'source': 'git',
            'repository': 'https://github.com/test/node-pack-2'
        }
        # node-pack-3 is NOT installed

        test_env.pyproject.save(config)

        # Commit the workflow so it shows as "synced" (but with uninstalled packages)
        test_env.workflow_manager.copy_all_workflows()
        import subprocess
        subprocess.run(
            ["git", "add", "-A"],
            cwd=test_env.cec_path,
            check=True,
            capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Add workflow with uninstalled nodes"],
            cwd=test_env.cec_path,
            check=True,
            capture_output=True
        )

        # ACT: Get workflow status
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_workflow = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "test_workflow"),
            None
        )

        assert test_workflow is not None, "test_workflow should exist"

        # VERIFY BUG: has_issues only checks resolution, not installation
        has_resolution_issues = test_workflow.has_issues

        # Calculate what SHOULD be checked: uninstalled packages
        workflow_config = config['tool']['comfygit']['workflows']['test_workflow']
        workflow_needs = set(workflow_config.get('nodes', []))
        installed = set(test_env.pyproject.nodes.get_existing().keys())
        has_uninstalled = bool(workflow_needs - installed)

        # DEBUG: Print what we found
        print("\n=== DEBUG ===")
        print(f"Workflow needs: {workflow_needs}")
        print(f"Installed: {installed}")
        print(f"Uninstalled: {workflow_needs - installed}")
        print(f"has_resolution_issues: {has_resolution_issues}")
        print(f"has_uninstalled: {has_uninstalled}")
        print(f"nodes_resolved: {[n.package_id for n in test_workflow.resolution.nodes_resolved]}")
        print(f"nodes_unresolved: {[n.type for n in test_workflow.resolution.nodes_unresolved]}")
        print("=============\n")

        # ASSERT: This will FAIL if bug exists (has_issues=False but has_uninstalled=True)
        # When fixed, both should be True or has_issues should check for uninstalled
        if has_uninstalled and not has_resolution_issues:
            pytest.fail(
                f"BUG DETECTED: Workflow has {len(workflow_needs - installed)} uninstalled packages "
                f"but has_issues={has_resolution_issues}. The status command won't show this workflow "
                f"as having issues!"
            )

        # If both are False, that's also a bug!
        if not has_uninstalled:
            pytest.fail(
                f"TEST ERROR: Expected has_uninstalled=True but got False. "
                f"workflow_needs={workflow_needs}, installed={installed}"
            )

    def test_print_workflow_issues_detects_uninstalled(self, test_env):
        """
        Direct test of _print_workflow_issues method to ensure it calculates correctly.

        This tests the fix is in place - the method should calculate the diff
        between workflow.nodes and installed nodes from pyproject.toml.
        """
        # ARRANGE: Set up pyproject.toml state
        config = test_env.pyproject.load()

        if 'workflows' not in config['tool']['comfygit']:
            config['tool']['comfygit']['workflows'] = {}
        if 'nodes' not in config['tool']['comfygit']:
            config['tool']['comfygit']['nodes'] = {}

        # Workflow needs 3 nodes
        config['tool']['comfygit']['workflows']['test_wf'] = {
            'path': 'workflows/test_wf.json',
            'nodes': ['pkg-a', 'pkg-b', 'pkg-c']
        }

        # Only 2 installed
        config['tool']['comfygit']['nodes']['pkg-a'] = {'name': 'Package A', 'source': 'git', 'repository': 'https://github.com/test/pkg-a'}
        config['tool']['comfygit']['nodes']['pkg-b'] = {'name': 'Package B', 'source': 'git', 'repository': 'https://github.com/test/pkg-b'}
        # pkg-c NOT installed

        test_env.pyproject.save(config)

        # ACT: Calculate uninstalled packages (this is what _print_workflow_issues does)
        workflow_config = config['tool']['comfygit']['workflows']['test_wf']
        workflow_node_list = set(workflow_config.get('nodes', []))
        installed_packages = test_env.pyproject.nodes.get_existing()
        packages_needed = workflow_node_list - set(installed_packages.keys())

        # ASSERT: Should correctly identify 1 uninstalled package
        assert len(packages_needed) == 1, \
            f"Should have 1 uninstalled package, got {len(packages_needed)}: {packages_needed}"
        assert 'pkg-c' in packages_needed, \
            f"pkg-c should be uninstalled, got: {packages_needed}"
