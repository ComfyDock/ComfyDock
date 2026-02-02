"""Test for bug: checkout -b fails with uncommitted changes to existing workflow.

This reproduces the exact user scenario where:
1. User is on a branch with a committed workflow
2. User modifies the workflow (uncommitted changes)
3. User runs 'cg checkout -b new-branch'
4. Expected: new branch is created with uncommitted changes preserved
5. Actual: Error about uncommitted changes that would be overwritten
"""
import json


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


class TestCheckoutBWithModifiedWorkflow:
    """Test checkout -b with modified (not new) uncommitted workflow."""

    def test_checkout_b_with_modified_workflow_should_preserve(self, test_env):
        """BUG: checkout -b should preserve uncommitted modifications to existing workflow.

        This is the exact user scenario:
        1. On branch 'right' with committed workflow 'default'
        2. User modifies 'default' workflow (moves a node)
        3. User runs 'cg checkout -b upper-right'
        4. Expected: new branch created, uncommitted changes preserved
        5. Actual: Error "Cannot switch to branch 'upper-right' with uncommitted workflow changes"

        The bug occurs because:
        - create_branch('upper-right', 'HEAD') creates branch from current HEAD
        - switch_branch('upper-right') with create=False triggers conflict detection
        - _would_overwrite_workflows() finds 'default' exists in target branch (because it was just created from HEAD!)
        - Incorrectly raises error about conflicts with itself
        """
        # ARRANGE: Create branch 'right' with committed workflow 'default'
        workflow_v1 = create_simple_workflow()
        commit_workflow_to_cec(test_env, "default", workflow_v1)

        test_env.create_branch("right")
        test_env.switch_branch("right")

        # Modify the workflow (simulates user moving a node)
        workflow_v2 = create_simple_workflow()
        workflow_v2["1"]["inputs"]["ckpt_name"] = "modified_model.safetensors"
        save_workflow_to_comfyui(test_env, "default", workflow_v2)

        # Verify uncommitted modification
        status = test_env.status()
        assert "default" in status.workflow.sync_status.modified, "Workflow should be modified"

        # ACT: Simulate 'cg checkout -b upper-right'
        # Use the new atomic operation that mimics git checkout -b
        test_env.create_and_switch_branch("upper-right", start_point="HEAD")

        # ASSERT: Uncommitted changes preserved
        workflow_path = test_env.comfyui_path / "user" / "default" / "workflows" / "default.json"
        assert workflow_path.exists(), "Workflow should exist after checkout -b"

        with open(workflow_path) as f:
            preserved_workflow = json.load(f)
        assert preserved_workflow == workflow_v2, "Uncommitted changes should be preserved"

        # Verify still shows as uncommitted on new branch
        status = test_env.status()
        assert "default" in status.workflow.sync_status.modified, "Should still show as modified"

    def test_checkout_b_with_new_uncommitted_workflow_should_preserve(self, test_env):
        """checkout -b should preserve new uncommitted workflows."""
        # ARRANGE: Create a new uncommitted workflow
        workflow = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "new_workflow", workflow)

        status = test_env.status()
        assert "new_workflow" in status.workflow.sync_status.new

        # ACT: Simulate 'cg checkout -b feature'
        test_env.create_and_switch_branch("feature", start_point="HEAD")

        # ASSERT: Uncommitted workflow preserved
        workflow_path = test_env.comfyui_path / "user" / "default" / "workflows" / "new_workflow.json"
        assert workflow_path.exists(), "New workflow should be preserved"

        status = test_env.status()
        assert "new_workflow" in status.workflow.sync_status.new
