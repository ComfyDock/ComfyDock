"""Integration tests for commit command with git-only changes.

Bug Report:
When pyproject.toml has uncommitted changes but workflows are synced,
the commit command refuses to commit with "No changes to commit - workflows
are already up to date", even though git has uncommitted changes.

This happens in scenarios like:
1. Node resolution without workflow JSON changes
2. Manual node additions via `cfd node add`
3. Constraint additions
4. Any pyproject.toml edits without workflow file changes

The CLI layer incorrectly checks ONLY workflow file sync status,
ignoring git uncommitted changes in .cec/pyproject.toml.
"""
import sys
from pathlib import Path

# Add parent dir to path for conftest import
sys.path.insert(0, str(Path(__file__).parent.parent))
from comfygit_core.models.shared import NodeInfo
from conftest import simulate_comfyui_save_workflow


class TestCommitWithGitChangesOnly:
    """Test that commit works when only git has changes (not workflow files)."""

    def test_commit_with_node_resolution_but_synced_workflow(self, test_env):
        """Test commit after node resolution when workflow JSON is unchanged.

        Scenario:
        1. Commit workflow with unresolved nodes
        2. Resolve nodes interactively (adds to pyproject.toml)
        3. Workflow JSON file doesn't change (nodes were already referenced)
        4. Run commit --allow-issues
        5. Expected: Commit succeeds (pyproject.toml has changes)
        6. Current bug: "No changes to commit - workflows are already up to date"
        """
        # ARRANGE: Create and commit a workflow
        workflow_data = {
            "nodes": [
                {"id": "1", "type": "CheckpointLoaderSimple", "widgets_values": ["model.safetensors"]},
                {"id": "2", "type": "SomeCustomNode", "widgets_values": []}
            ],
            "links": []
        }

        simulate_comfyui_save_workflow(test_env, "test_wf", workflow_data)

        # Commit v1 (with unresolved node)
        test_env.git_manager.commit_all("v1: Initial workflow")

        # Copy workflow to .cec (simulate it being tracked)
        test_env.workflow_manager.copy_all_workflows()
        test_env.git_manager.commit_all("v1: Sync workflow")

        # Now add a node to pyproject.toml (simulating resolution)
        # This represents what happens when user resolves nodes
        node_info = NodeInfo(
            name="custom-node-package",
            registry_id="custom-node-package",
            source="registry",
            version="1.0.0"
        )
        test_env.pyproject.nodes.add(node_info, "custom-node-package")
        # Save changes manually
        config = test_env.pyproject.load()
        test_env.pyproject.save(config)

        # Verify state BEFORE commit attempt
        workflow_status = test_env.workflow_manager.get_workflow_status()
        assert not workflow_status.sync_status.has_changes, \
            "Workflow should be synced (no file changes)"

        has_git_changes = test_env.git_manager.has_uncommitted_changes()
        assert has_git_changes, \
            "Git should have uncommitted changes (pyproject.toml modified)"

        # ACT: Try to commit
        # The core layer should recognize git changes even if workflows are synced
        # THIS IS THE BUG - core layer doesn't check git, only workflow sync

        # We're testing the CORE layer method directly
        # The CLI would call execute_commit() after checking workflow status
        # But execute_commit() should handle this case

        # Simulate what CLI does: check if committable
        # Current bug: CLI only checks workflow_status.sync_status.has_changes
        # and exits early, never calling execute_commit()

        # For now, directly call execute_commit (which CLI should reach)
        test_env.execute_commit(
            workflow_status=workflow_status,
            message="Add resolved nodes",
            allow_issues=True
        )

        # ASSERT: Commit should have succeeded
        # Check git history
        versions = test_env.get_commit_history()
        assert len(versions) >= 3, \
            "Should have created new commit (v1, v1-sync, v3-node-resolution)"

        # Verify no uncommitted changes remain
        assert not test_env.git_manager.has_uncommitted_changes(), \
            "Git should be clean after commit"

        # Verify node is in committed state
        committed_nodes = test_env.pyproject.nodes.get_existing()
        assert "custom-node-package" in committed_nodes

    def test_commit_with_manual_node_addition_no_workflows(self, test_env):
        """Test commit after adding node via CLI when no workflows exist.

        Scenario:
        1. Environment has no workflows
        2. User adds node: `cfd node add rgthree-comfy`
        3. pyproject.toml updated
        4. Run commit
        5. Expected: Commit succeeds (pyproject.toml has changes)
        6. Current bug: "No workflows found to commit" (line 786-788)
        """
        # ARRANGE: Start with clean environment (no workflows)
        test_env.git_manager.commit_all("v1: Empty environment")

        # Add a node (simulating `cfd node add rgthree-comfy`)
        node_info = NodeInfo(
            name="rgthree-comfy",
            registry_id="rgthree-comfy",
            source="registry",
            version="1.5.0"
        )
        test_env.pyproject.nodes.add(node_info, "rgthree-comfy")
        config = test_env.pyproject.load()
        test_env.pyproject.save(config)

        # Verify state
        workflow_status = test_env.workflow_manager.get_workflow_status()
        assert workflow_status.sync_status.total_count == 0, \
            "Should have no workflows"

        has_git_changes = test_env.git_manager.has_uncommitted_changes()
        assert has_git_changes, \
            "Git should have uncommitted changes (node added to pyproject.toml)"

        # ACT: Try to commit
        # This tests core layer's execute_commit()
        test_env.execute_commit(
            workflow_status=workflow_status,
            message="Add rgthree-comfy",
            allow_issues=False
        )

        # ASSERT: Commit should succeed even without workflows
        versions = test_env.get_commit_history()
        assert len(versions) == 2, \
            "Should have created new commit"

        # Verify no uncommitted changes
        assert not test_env.git_manager.has_uncommitted_changes()

        # Verify node is committed
        committed_nodes = test_env.pyproject.nodes.get_existing()
        assert "rgthree-comfy" in committed_nodes

    def test_commit_with_constraint_addition_no_workflow_changes(self, test_env):
        """Test commit after adding constraint when workflows unchanged.

        Scenario:
        1. User adds constraint: `cfd constraint add "numpy<2.0"`
        2. pyproject.toml updated
        3. Workflows unchanged
        4. Run commit
        5. Expected: Commit succeeds
        6. Current bug: "No changes to commit - workflows are already up to date"
        """
        # ARRANGE: Create initial commit
        test_env.git_manager.commit_all("v1: Initial")

        # Add constraint
        test_env.add_constraint("numpy<2.0")

        # Verify state
        workflow_status = test_env.workflow_manager.get_workflow_status()
        assert not workflow_status.sync_status.has_changes, \
            "Workflows should be synced"

        has_git_changes = test_env.git_manager.has_uncommitted_changes()
        assert has_git_changes, \
            "Git should have uncommitted changes (constraint added)"

        # ACT: Commit
        test_env.execute_commit(
            workflow_status=workflow_status,
            message="Add numpy constraint",
            allow_issues=False
        )

        # ASSERT: Should succeed
        assert not test_env.git_manager.has_uncommitted_changes()

        # Verify constraint is committed
        constraints = test_env.list_constraints()
        assert "numpy<2.0" in constraints

    def test_commit_with_both_workflow_and_git_changes(self, test_env):
        """Test commit with BOTH workflow file changes AND git changes.

        This should work with current implementation - testing baseline.
        """
        # ARRANGE: Create workflow
        workflow_data = {
            "nodes": [{"id": "1", "type": "CheckpointLoaderSimple", "widgets_values": ["model.safetensors"]}],
            "links": []
        }
        simulate_comfyui_save_workflow(test_env, "test", workflow_data)

        # Also add a node to pyproject
        node_info = NodeInfo(name="test-node", registry_id="test-node", source="registry", version="1.0")
        test_env.pyproject.nodes.add(node_info, "test-node")
        config = test_env.pyproject.load()
        test_env.pyproject.save(config)

        # Verify BOTH changes exist
        workflow_status = test_env.workflow_manager.get_workflow_status()
        assert workflow_status.sync_status.has_changes, "Workflow should have changes"
        assert test_env.git_manager.has_uncommitted_changes(), "Git should have changes"

        # ACT: Commit (this should work)
        test_env.execute_commit(
            workflow_status=workflow_status,
            message="Add workflow and node",
            allow_issues=True
        )

        # ASSERT: Should succeed
        assert not test_env.git_manager.has_uncommitted_changes()

    def test_no_changes_at_all_returns_gracefully(self, test_env):
        """Test that commit with no changes at all is handled gracefully."""
        # ARRANGE: Clean state
        test_env.git_manager.commit_all("v1: Initial")

        # No changes made
        workflow_status = test_env.workflow_manager.get_workflow_status()
        assert not workflow_status.sync_status.has_changes
        assert not test_env.git_manager.has_uncommitted_changes()

        # ACT: Try to commit (should be no-op)
        test_env.execute_commit(
            workflow_status=workflow_status,
            message="Nothing to commit",
            allow_issues=False
        )

        # ASSERT: Should not create new commit
        versions = test_env.get_commit_history()
        assert len(versions) == 1, "Should not create new commit when no changes"


class TestCoreLayerCommitAPI:
    """Test the proposed core layer API for checking committable changes."""

    def test_has_committable_changes_with_workflow_changes(self, test_env):
        """Test new API detects workflow file changes."""
        workflow_data = {
            "nodes": [{"id": "1", "type": "CheckpointLoaderSimple"}],
            "links": []
        }
        simulate_comfyui_save_workflow(test_env, "test", workflow_data)

        # Should detect workflow changes
        # THIS METHOD DOESN'T EXIST YET - test will fail until implemented
        assert test_env.has_committable_changes(), \
            "Should detect workflow file changes"

    def test_has_committable_changes_with_git_changes(self, test_env):
        """Test new API detects git changes without workflow changes."""
        # Add node to pyproject.toml
        node_info = NodeInfo(name="test", registry_id="test", source="registry", version="1.0")
        test_env.pyproject.nodes.add(node_info, "test")
        config = test_env.pyproject.load()
        test_env.pyproject.save(config)

        # Should detect git changes
        assert test_env.has_committable_changes(), \
            "Should detect git changes even without workflow changes"

    def test_has_committable_changes_with_both(self, test_env):
        """Test new API detects both types of changes."""
        # Workflow change
        workflow_data = {"nodes": [{"id": "1", "type": "Test"}], "links": []}
        simulate_comfyui_save_workflow(test_env, "test", workflow_data)

        # Git change
        node_info = NodeInfo(name="test", registry_id="test", source="registry", version="1.0")
        test_env.pyproject.nodes.add(node_info, "test")
        config = test_env.pyproject.load()
        test_env.pyproject.save(config)

        # Should detect both
        assert test_env.has_committable_changes()

    def test_has_committable_changes_with_no_changes(self, test_env):
        """Test new API returns False when truly no changes."""
        test_env.git_manager.commit_all("v1: Initial")

        # Should return False
        assert not test_env.has_committable_changes(), \
            "Should return False when no changes at all"
