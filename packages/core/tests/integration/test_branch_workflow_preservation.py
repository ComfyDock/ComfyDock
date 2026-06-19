"""Integration tests for workflow preservation and snapshot materialization.

Creating a new branch preserves current uncommitted workflow work because the
new branch starts from the current tree. Existing branch/commit navigation is
snapshot-strict: dirty state must be committed or discarded first, and the
target snapshot is materialized exactly into ComfyUI.

Reference: docs/contexts/plan/git-branch-workflow-preservation.md
"""
import json

import pytest
from comfygit_core.models.exceptions import CDEnvironmentError


def create_simple_workflow():
    """Create a simple test workflow."""
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "test_model.safetensors"}
        }
    }


def save_workflow_to_comfyui(env, name: str, workflow_data: dict):
    """Simulate ComfyUI saving a workflow (writes to ComfyUI directory)."""
    workflow_path = env.comfyui_path / "user" / "default" / "workflows" / f"{name}.json"
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    with open(workflow_path, 'w') as f:
        json.dump(workflow_data, f, indent=2)


def commit_workflow_to_cec(env, name: str, workflow_data: dict):
    """Commit a workflow to .cec (simulates user committing workflow)."""
    # Save to ComfyUI
    save_workflow_to_comfyui(env, name, workflow_data)

    # Copy to .cec (simulates commit process)
    cec_workflows_dir = env.cec_path / "workflows"
    cec_workflows_dir.mkdir(parents=True, exist_ok=True)
    cec_workflow_path = cec_workflows_dir / f"{name}.json"
    with open(cec_workflow_path, 'w') as f:
        json.dump(workflow_data, f, indent=2)

    # Git commit
    env.git_manager.commit_all(f"Add workflow {name}")


class TestCheckoutBranchPreservesUncommittedWorkflows:
    """Test that 'checkout -b' preserves uncommitted workflows (Phase 1)."""

    def test_checkout_b_preserves_uncommitted_workflow(self, test_env):
        """Creating new branch should preserve uncommitted workflows.

        This is the primary bug scenario: user creates workflow, then does
        'cg checkout -b feature' and expects workflow to still exist.
        """
        # ARRANGE: Create uncommitted workflow in ComfyUI
        workflow = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "test_workflow", workflow)

        # Verify workflow exists in ComfyUI but not in .cec
        comfyui_workflow = test_env.comfyui_path / "user" / "default" / "workflows" / "test_workflow.json"
        assert comfyui_workflow.exists(), "Workflow should exist in ComfyUI"

        cec_workflow = test_env.cec_path / "workflows" / "test_workflow.json"
        assert not cec_workflow.exists(), "Workflow should NOT be in .cec (uncommitted)"

        # Verify status shows uncommitted workflow
        status = test_env.status()
        assert "test_workflow" in status.workflow.sync_status.new

        # ACT: Create new branch (simulates 'cg checkout -b feature')
        test_env.create_and_switch_branch("feature", start_point="HEAD")

        # ASSERT: Workflow still exists in ComfyUI
        assert comfyui_workflow.exists(), "BUG: Workflow should be preserved during checkout -b"

        # Verify workflow content unchanged
        with open(comfyui_workflow) as f:
            preserved_workflow = json.load(f)
        assert preserved_workflow == workflow, "Workflow content should be unchanged"

        # Verify status still shows it as uncommitted
        status = test_env.status()
        assert "test_workflow" in status.workflow.sync_status.new

    def test_checkout_b_preserves_multiple_uncommitted_workflows(self, test_env):
        """Creating branch should preserve all uncommitted workflows."""
        # ARRANGE: Create multiple uncommitted workflows
        workflow1 = create_simple_workflow()
        workflow2 = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "workflow1", workflow1)
        save_workflow_to_comfyui(test_env, "workflow2", workflow2)

        # ACT: Create new branch
        test_env.create_and_switch_branch("feature")

        # ASSERT: Both workflows preserved
        wf1_path = test_env.comfyui_path / "user" / "default" / "workflows" / "workflow1.json"
        wf2_path = test_env.comfyui_path / "user" / "default" / "workflows" / "workflow2.json"
        assert wf1_path.exists(), "workflow1 should be preserved"
        assert wf2_path.exists(), "workflow2 should be preserved"


class TestSwitchBranchConflictDetection:
    """Test that existing-branch switches require clean snapshot state."""

    def test_switch_blocks_uncommitted_new_workflow(self, test_env):
        """Switching existing branches should not carry workflow drafts across snapshots."""
        # ARRANGE: Create two branches
        commit_workflow_to_cec(test_env, "committed_workflow", create_simple_workflow())

        test_env.create_branch("feature")
        test_env.switch_branch("feature")

        # Create uncommitted workflow on feature branch
        new_workflow = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "feature_workflow", new_workflow)

        # Verify uncommitted
        status = test_env.status()
        assert "feature_workflow" in status.workflow.sync_status.new

        # ACT & ASSERT: Switch back to main should be blocked until commit/discard.
        with pytest.raises(CDEnvironmentError, match="uncommitted changes"):
            test_env.switch_branch("main")

    def test_switch_blocks_when_would_overwrite(self, test_env):
        """Switching should error when uncommitted workflow exists in target branch.

        Conflict scenario: uncommitted workflow with same name exists in target.
        This matches git behavior blocking checkout when changes would be overwritten.
        """
        # ARRANGE: Create workflow on main and commit it
        workflow_v1 = create_simple_workflow()
        commit_workflow_to_cec(test_env, "shared_workflow", workflow_v1)

        # Create feature branch
        test_env.create_branch("feature")
        test_env.switch_branch("feature")

        # Modify the workflow on feature (uncommitted)
        workflow_v2 = create_simple_workflow()
        workflow_v2["1"]["inputs"]["ckpt_name"] = "modified_model.safetensors"
        save_workflow_to_comfyui(test_env, "shared_workflow", workflow_v2)

        # Verify uncommitted modification
        status = test_env.status()
        assert "shared_workflow" in status.workflow.sync_status.modified

        # ACT & ASSERT: Switch should error until the working snapshot is clean.
        with pytest.raises(CDEnvironmentError, match="uncommitted changes"):
            test_env.switch_branch("main")

        # Verify workflow still has modified version
        wf_path = test_env.comfyui_path / "user" / "default" / "workflows" / "shared_workflow.json"
        with open(wf_path) as f:
            current = json.load(f)
        assert current == workflow_v2, "Workflow should not be overwritten"

    def test_switch_blocks_when_new_workflow_exists_in_target(self, test_env):
        """Switching should error when uncommitted new workflow exists in target.

        This tests the case where user creates workflow with a name that already
        exists in the target branch (but user hasn't committed it yet).
        """
        # ARRANGE: Create workflow on main and commit
        workflow_main = create_simple_workflow()
        commit_workflow_to_cec(test_env, "test_workflow", workflow_main)

        # Create feature branch (without the workflow)
        test_env.create_branch("feature")
        test_env.switch_branch("feature")

        # Delete workflow from feature branch
        (test_env.cec_path / "workflows" / "test_workflow.json").unlink()
        test_env.git_manager.commit_all("Remove test_workflow")

        # User creates new workflow with same name (uncommitted)
        workflow_new = create_simple_workflow()
        workflow_new["1"]["inputs"]["ckpt_name"] = "different_model.safetensors"
        save_workflow_to_comfyui(test_env, "test_workflow", workflow_new)

        # ACT & ASSERT: Switch to main should error until the working snapshot is clean.
        with pytest.raises(CDEnvironmentError, match="uncommitted changes"):
            test_env.switch_branch("main")

    def test_switch_blocks_captured_working_snapshot_changes(self, test_env):
        """Save-time capture creates `.cec` changes, which must block branch switches."""
        # ARRANGE: Create a branch from a clean snapshot.
        test_env.git_manager.commit_all("initial")
        test_env.create_branch("feature")
        test_env.switch_branch("feature")

        # Capture simulates Manager save handling: ComfyUI and .cec now match,
        # but the environment repository has uncommitted tracked-state changes.
        workflow = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "captured_workflow", workflow)
        test_env.workflow_manager.capture_workflow("captured_workflow")

        assert not test_env.workflow_manager.get_workflow_sync_status().has_changes
        assert test_env.git_manager.has_uncommitted_changes()

        # ACT & ASSERT: Existing-branch switch is blocked, even though file-level
        # workflow sync appears clean.
        with pytest.raises(CDEnvironmentError, match="uncommitted changes"):
            test_env.switch_branch("main")


class TestRestoreAllFromCecParameter:
    """Test the preserve_uncommitted parameter on restore_all_from_cec()."""

    def test_restore_with_preserve_false_deletes_uncommitted(self, test_env):
        """restore_all_from_cec(preserve_uncommitted=False) should delete uncommitted.

        This is the current behavior - used for rollback operations.
        """
        # ARRANGE: Create uncommitted workflow
        workflow = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "uncommitted", workflow)

        wf_path = test_env.comfyui_path / "user" / "default" / "workflows" / "uncommitted.json"
        assert wf_path.exists()

        # ACT: Restore with preserve=False (current behavior)
        test_env.workflow_manager.restore_all_from_cec(preserve_uncommitted=False)

        # ASSERT: Uncommitted workflow deleted
        assert not wf_path.exists(), "Should delete uncommitted workflows"

    def test_restore_with_preserve_true_keeps_uncommitted(self, test_env):
        """restore_all_from_cec(preserve_uncommitted=True) should keep uncommitted.

        This mode is used when creating a new branch from the current tree.
        """
        # ARRANGE: Create uncommitted workflow
        workflow = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "uncommitted", workflow)

        wf_path = test_env.comfyui_path / "user" / "default" / "workflows" / "uncommitted.json"
        assert wf_path.exists()

        # ACT: Restore with preserve=True (new behavior)
        test_env.workflow_manager.restore_all_from_cec(preserve_uncommitted=True)

        # ASSERT: Uncommitted workflow preserved
        assert wf_path.exists(), "Should preserve uncommitted workflows"

        # Verify content unchanged
        with open(wf_path) as f:
            preserved = json.load(f)
        assert preserved == workflow

    def test_restore_with_preserve_true_still_restores_committed(self, test_env):
        """preserve_uncommitted=True should still restore committed workflows."""
        # ARRANGE: Create committed workflow in .cec but not in ComfyUI
        cec_workflows_dir = test_env.cec_path / "workflows"
        cec_workflows_dir.mkdir(parents=True, exist_ok=True)

        workflow = create_simple_workflow()
        cec_wf_path = cec_workflows_dir / "committed.json"
        with open(cec_wf_path, 'w') as f:
            json.dump(workflow, f)

        test_env.git_manager.commit_all("Add committed workflow")

        # Verify NOT in ComfyUI
        comfyui_wf_path = test_env.comfyui_path / "user" / "default" / "workflows" / "committed.json"
        assert not comfyui_wf_path.exists()

        # ACT: Restore with preserve=True
        test_env.workflow_manager.restore_all_from_cec(preserve_uncommitted=True)

        # ASSERT: Committed workflow restored
        assert comfyui_wf_path.exists(), "Should restore committed workflows"
        with open(comfyui_wf_path) as f:
            restored = json.load(f)
        assert restored == workflow


class TestRollbackStillDestructive:
    """Test that rollback/checkout/reset remain destructive (preserve_uncommitted=False)."""

    def test_checkout_ref_still_destructive(self, test_env):
        """checkout(ref) should still delete uncommitted workflows."""
        # ARRANGE: Create v1 and v2
        commit_workflow_to_cec(test_env, "v1_workflow", create_simple_workflow())
        v1_hash = test_env.get_commit_history(limit=1)[0].hash

        # Create uncommitted workflow
        save_workflow_to_comfyui(test_env, "uncommitted", create_simple_workflow())

        # ACT: Checkout v1 with force
        test_env.checkout(v1_hash, force=True)

        # ASSERT: Uncommitted workflow deleted (destructive rollback)
        uncommitted_path = test_env.comfyui_path / "user" / "default" / "workflows" / "uncommitted.json"
        assert not uncommitted_path.exists(), "checkout should be destructive"

    def test_reset_hard_still_destructive(self, test_env):
        """reset(mode='hard') should still delete uncommitted workflows."""
        # ARRANGE: Create commit
        test_env.git_manager.commit_all("v1")

        # Create uncommitted workflow
        save_workflow_to_comfyui(test_env, "uncommitted", create_simple_workflow())

        # ACT: Hard reset
        test_env.reset(ref="HEAD", mode="hard", force=True)

        # ASSERT: Uncommitted workflow deleted
        uncommitted_path = test_env.comfyui_path / "user" / "default" / "workflows" / "uncommitted.json"
        assert not uncommitted_path.exists(), "reset --hard should be destructive"


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_switch_deletes_workflows_when_cec_dir_doesnt_exist(self, test_env):
        """BUG REPRODUCTION: Workflows should be deleted when switching to branch without .cec/workflows/.

        This is the exact bug scenario reported:
        1. Branch 'test' created via checkout -b (never has .cec/workflows/ directory)
        2. Branch 'test2' created from 'test', workflow committed (creates .cec/workflows/)
        3. Switch back to 'test' → git deletes .cec/workflows/ directory
        4. BUG: Workflow stays in ComfyUI because restore_all_from_cec() returns early

        Expected behavior (matching git):
        - Workflows should be deleted from ComfyUI when switching to branch without them
        """
        # ARRANGE: Create branch 'test' from initial state (no workflows ever created)
        test_env.git_manager.commit_all("initial commit")
        test_env.create_branch("test")
        test_env.switch_branch("test")

        # Delete .cec/workflows/ to simulate git not tracking empty dirs
        # (WorkflowManager creates it, but git would not have it in the tree)
        import shutil
        cec_workflows = test_env.cec_path / "workflows"
        if cec_workflows.exists():
            shutil.rmtree(cec_workflows)

        assert not cec_workflows.exists(), "Branch 'test' should not have .cec/workflows/ directory"

        # Create branch 'test2' from 'test'
        test_env.create_branch("test2")
        test_env.switch_branch("test2")

        # Create and commit workflow on test2
        workflow = create_simple_workflow()
        commit_workflow_to_cec(test_env, "default", workflow)

        # Verify workflow exists in both .cec and ComfyUI
        assert cec_workflows.exists(), ".cec/workflows/ should exist after commit"
        assert (cec_workflows / "default.json").exists(), "default.json should be in .cec"

        comfyui_workflow = test_env.comfyui_path / "user" / "default" / "workflows" / "default.json"
        assert comfyui_workflow.exists(), "default.json should be in ComfyUI"

        # ACT: Switch back to 'test' (which never had .cec/workflows/)
        test_env.switch_branch("test")

        # ASSERT: Git should delete .cec/workflows/ directory
        assert not cec_workflows.exists(), "Git should delete .cec/workflows/ when switching to 'test'"

        # CRITICAL ASSERTION: Workflow should be deleted from ComfyUI
        # This is the bug - workflow stays because restore_all_from_cec() returns early
        assert not comfyui_workflow.exists(), (
            "BUG: Workflow should be deleted from ComfyUI when switching to branch without it. "
            "Git deleted .cec/workflows/, but restore_all_from_cec() returns early without cleanup."
        )

    def test_switch_with_no_workflows(self, test_env):
        """Switching branches with no workflows should work."""
        # ARRANGE: Create branch with no workflows
        test_env.git_manager.commit_all("initial")
        test_env.create_branch("empty")

        # ACT: Switch to empty branch
        test_env.switch_branch("empty")

        # ASSERT: No errors
        assert test_env.get_current_branch() == "empty"

    def test_switch_blocks_uncommitted_workflow_even_when_target_branch_empty(self, test_env):
        """Uncommitted workflows are not carried to an existing empty branch."""
        # ARRANGE: Create empty feature branch
        test_env.git_manager.commit_all("initial")
        test_env.create_branch("feature")
        test_env.switch_branch("feature")

        # Create uncommitted workflow
        save_workflow_to_comfyui(test_env, "test", create_simple_workflow())

        # ACT & ASSERT: Switch back to main is blocked until commit/discard.
        with pytest.raises(CDEnvironmentError, match="uncommitted changes"):
            test_env.switch_branch("main")

    def test_force_checkout_cleans_captured_workflow_absent_from_target(self, test_env):
        """Force checkout should clean uncommitted `.cec` workflow files before restore."""
        # ARRANGE: main starts empty; feature captures a workflow but does not commit it.
        test_env.git_manager.commit_all("initial")
        test_env.create_branch("feature")
        test_env.switch_branch("feature")

        save_workflow_to_comfyui(test_env, "test", create_simple_workflow())
        test_env.workflow_manager.capture_workflow("test")

        cec_path = test_env.cec_path / "workflows" / "test.json"
        wf_path = test_env.comfyui_path / "user" / "default" / "workflows" / "test.json"
        assert cec_path.exists()
        assert wf_path.exists()

        # ACT: Manager's force-switch path uses checkout(..., force=True).
        test_env.checkout("main", force=True)

        # ASSERT: Uncommitted .cec file is cleaned, then ComfyUI is restored to
        # the target snapshot and the workflow disappears there too.
        assert not cec_path.exists()
        assert not wf_path.exists()

    def test_create_branch_from_commit_preserves_uncommitted(self, test_env):
        """Creating branch from specific commit should preserve uncommitted."""
        # ARRANGE: Create commits
        test_env.git_manager.commit_all("v1")
        v1_hash = test_env.get_commit_history(limit=1)[0].hash

        (test_env.cec_path / "file.txt").write_text("v2")
        test_env.git_manager.commit_all("v2")

        # Create uncommitted workflow
        save_workflow_to_comfyui(test_env, "uncommitted", create_simple_workflow())

        # ACT: Create branch from v1
        test_env.create_and_switch_branch("from-v1", start_point=v1_hash)

        # ASSERT: Uncommitted workflow preserved
        wf_path = test_env.comfyui_path / "user" / "default" / "workflows" / "uncommitted.json"
        assert wf_path.exists(), "Should preserve uncommitted"
