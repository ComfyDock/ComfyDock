"""Integration test for workflow resolution cleanup bug.

Bug Report:
When a user:
1. Commits workflow 'default'
2. Runs ComfyUI which saves 'depthflow_v2' (new workflow appears)
3. Resolves 'depthflow_v2'
4. Runs ComfyUI again which saves 'depthflow_v2_1' and deletes 'default'
5. Resolves 'depthflow_v2_1'

Expected: After step 5, pyproject.toml should only have 'depthflow_v2' and 'depthflow_v2_1'
Actual bug: pyproject.toml has 'default', 'depthflow_v2', and 'depthflow_v2_1'

Root cause: Workflow resolution (apply_resolution) doesn't clean up deleted workflows.
The cleanup only happens during commit, but users may resolve multiple times before committing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.pyproject_assertions import PyprojectAssertions
from helpers.workflow_builder import WorkflowBuilder


class TestWorkflowResolutionCleanup:
    """Test that workflow resolution cleans up deleted workflows from pyproject.toml."""

    def test_resolve_cleans_up_deleted_workflows(self, test_env, test_workspace):
        """Test that resolving a new workflow removes deleted workflows from pyproject.

        This replicates the exact bug from the terminal output:
        1. Commit 'default' workflow
        2. ComfyUI creates 'depthflow_showcase_v2', resolve it, commit
        3. ComfyUI creates 'depthflow_showcase_v2_1' and deletes 'default'
        4. Resolve 'depthflow_showcase_v2_1'
        5. BUG: pyproject.toml still contains 'default' section

        Expected: After step 4, 'default' section should be removed
        """
        # ARRANGE: Create test models
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("model1.safetensors", "checkpoints", size_mb=4)
        builder.index_all()

        # Step 1: Create and commit 'default' workflow
        workflow1 = WorkflowBuilder().add_checkpoint_loader("model1.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "default", workflow1)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add default workflow")

        # Verify 'default' exists
        assertions = PyprojectAssertions(test_env)
        assertions.has_workflow("default")

        # Step 2: ComfyUI creates 'depthflow_showcase_v2', resolve and commit
        workflow2 = WorkflowBuilder().add_checkpoint_loader("model1.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "depthflow_showcase_v2", workflow2)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add depthflow_showcase_v2")

        # Verify both workflows exist (reload assertions to get fresh config)
        assertions = PyprojectAssertions(test_env)
        assertions.has_workflow("default")
        assertions.has_workflow("depthflow_showcase_v2")

        # Step 3: ComfyUI creates 'depthflow_showcase_v2_1' and deletes 'default'
        # (simulates user using "Save As" in ComfyUI, then deleting old workflow)
        (test_env.comfyui_path / "user" / "default" / "workflows" / "default.json").unlink()
        workflow3 = WorkflowBuilder().add_checkpoint_loader("model1.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "depthflow_showcase_v2_1", workflow3)

        # Verify status shows deletion
        workflow_status = test_env.workflow_manager.get_workflow_status()
        assert "default" in workflow_status.sync_status.deleted, \
            "Status should show 'default' as deleted"
        assert "depthflow_showcase_v2_1" in workflow_status.sync_status.new, \
            "Status should show 'depthflow_showcase_v2_1' as new"

        # ACT: Resolve the new workflow (this is where the bug occurs)
        # In real usage, user runs: cfd workflow resolve "depthflow_showcase_v2_1"
        new_wf_analysis = next(
            (wf for wf in workflow_status.analyzed_workflows
             if wf.name == "depthflow_showcase_v2_1"),
            None
        )
        assert new_wf_analysis is not None, "Should find new workflow analysis"

        # Apply resolution (this is what happens during resolve command)
        test_env.workflow_manager.apply_resolution(new_wf_analysis.resolution)

        # ASSERT: After resolution, deleted workflows should be removed
        config = test_env.pyproject.load()
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})

        assert "default" not in workflows, \
            "BUG: Deleted workflow 'default' should be removed after resolution"

        assert "depthflow_showcase_v2" in workflows, \
            "Existing workflow 'depthflow_showcase_v2' should remain"

        assert "depthflow_showcase_v2_1" in workflows, \
            "Newly resolved workflow 'depthflow_showcase_v2_1' should exist"

    def test_resolve_cleans_up_orphaned_models_after_deletion(self, test_env, test_workspace):
        """Test that resolving workflows cleans up orphaned models.

        Scenario:
        1. Commit workflow 'wf1' with unique model A
        2. Commit workflow 'wf2' with unique model B
        3. Delete 'wf1' in ComfyUI
        4. Resolve 'wf2' (no changes)
        5. Expected: Model A removed from global table (orphaned)
        """
        # ARRANGE: Create unique models
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("unique_a.safetensors", "checkpoints", size_mb=4)
        builder.add_model("unique_b.safetensors", "checkpoints", size_mb=4)
        builder.index_all()

        # Create and commit wf1 with model A
        wf1 = WorkflowBuilder().add_checkpoint_loader("unique_a.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "wf1", wf1)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add wf1")

        # Create and commit wf2 with model B
        wf2 = WorkflowBuilder().add_checkpoint_loader("unique_b.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "wf2", wf2)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add wf2")

        # Get model hashes
        config = test_env.pyproject.load()
        wf1_models = config["tool"]["comfygit"]["workflows"]["wf1"]["models"]
        wf2_models = config["tool"]["comfygit"]["workflows"]["wf2"]["models"]
        model_a_hash = wf1_models[0]["hash"]
        model_b_hash = wf2_models[0]["hash"]

        # Verify both models in global table
        global_models = config["tool"]["comfygit"]["models"]
        assert model_a_hash in global_models
        assert model_b_hash in global_models

        # ACT: Delete wf1 and resolve wf2
        (test_env.comfyui_path / "user" / "default" / "workflows" / "wf1.json").unlink()

        workflow_status = test_env.workflow_manager.get_workflow_status()

        # Resolve wf2 (triggers cleanup)
        wf2_analysis = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "wf2"),
            None
        )
        test_env.workflow_manager.apply_resolution(wf2_analysis.resolution)

        # ASSERT: Model A should be removed (orphaned)
        config = test_env.pyproject.load()
        global_models = config["tool"]["comfygit"]["models"]

        assert model_a_hash not in global_models, \
            "BUG: Orphaned model A should be removed during resolution"

        assert model_b_hash in global_models, \
            "Model B should remain (still referenced by wf2)"

    def test_resolve_multiple_workflows_cleans_up_correctly(self, test_env, test_workspace):
        """Test resolving multiple new workflows while deleting others.

        Complex scenario:
        1. Commit workflows A, B, C
        2. Delete A, modify B, add D
        3. Resolve B (modified) - should trigger cleanup of A
        4. Resolve D (new) - cleanup should still work
        """
        # ARRANGE: Create models
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("ma.safetensors", "checkpoints")
        builder.add_model("mb.safetensors", "checkpoints")
        builder.add_model("mc.safetensors", "checkpoints")
        builder.add_model("md.safetensors", "checkpoints")
        builder.index_all()

        # Create and commit A, B, C
        for name, model in [("wf_a", "ma.safetensors"),
                            ("wf_b", "mb.safetensors"),
                            ("wf_c", "mc.safetensors")]:
            wf = WorkflowBuilder().add_checkpoint_loader(model).build()
            simulate_comfyui_save_workflow(test_env, name, wf)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add A, B, C")

        # ACT: Delete A, modify B, add D
        (test_env.comfyui_path / "user" / "default" / "workflows" / "wf_a.json").unlink()

        wf_b_modified = (
            WorkflowBuilder()
            .add_checkpoint_loader("mb.safetensors")
            .add_lora_loader("md.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "wf_b", wf_b_modified)

        wf_d = WorkflowBuilder().add_checkpoint_loader("md.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "wf_d", wf_d)

        workflow_status = test_env.workflow_manager.get_workflow_status()

        # Resolve B first (modified)
        wf_b_analysis = next(wf for wf in workflow_status.analyzed_workflows if wf.name == "wf_b")
        test_env.workflow_manager.apply_resolution(wf_b_analysis.resolution)

        # Check that A is removed after resolving B
        config = test_env.pyproject.load()
        workflows = config["tool"]["comfygit"]["workflows"]
        assert "wf_a" not in workflows, "wf_a should be removed after resolving wf_b"

        # Resolve D (new)
        wf_d_analysis = next(wf for wf in workflow_status.analyzed_workflows if wf.name == "wf_d")
        test_env.workflow_manager.apply_resolution(wf_d_analysis.resolution)

        # ASSERT: Final state should be correct
        config = test_env.pyproject.load()
        workflows = config["tool"]["comfygit"]["workflows"]

        assert "wf_a" not in workflows, "wf_a should remain removed"
        assert "wf_b" in workflows, "wf_b should exist"
        assert "wf_c" in workflows, "wf_c should exist"
        assert "wf_d" in workflows, "wf_d should exist"

    def test_resolve_cleans_up_never_committed_workflows(self, test_env, test_workspace):
        """Test that resolving cleans up workflows that were resolved but never committed.

        This is the exact scenario from the user's bug report:
        1. Resolve workflow 'wf1' (writes to pyproject) but DON'T commit
        2. Delete 'wf1' from ComfyUI
        3. Create and resolve 'wf2'
        4. Expected: 'wf1' should be removed from pyproject (even though never committed)
        5. Bug: 'wf1' remains in pyproject because it's not in .cec (sync_status.deleted doesn't include it)
        """
        # ARRANGE: Create models
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("m1.safetensors", "checkpoints")
        builder.add_model("m2.safetensors", "checkpoints")
        builder.index_all()

        # Step 1: Create and resolve 'wf1' WITHOUT committing
        wf1 = WorkflowBuilder().add_checkpoint_loader("m1.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "wf1", wf1)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        wf1_analysis = next(wf for wf in workflow_status.analyzed_workflows if wf.name == "wf1")
        test_env.workflow_manager.apply_resolution(wf1_analysis.resolution)

        # Verify wf1 is in pyproject
        config = test_env.pyproject.load()
        workflows = config["tool"]["comfygit"]["workflows"]
        assert "wf1" in workflows, "wf1 should be in pyproject after resolution"

        # Verify wf1 is NOT in .cec (never committed)
        assert not (test_env.cec_path / "workflows" / "wf1.json").exists(), \
            "wf1 should NOT be in .cec (never committed)"

        # Step 2: Delete wf1 from ComfyUI
        (test_env.comfyui_path / "user" / "default" / "workflows" / "wf1.json").unlink()

        # Step 3: Create and resolve wf2
        wf2 = WorkflowBuilder().add_checkpoint_loader("m2.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "wf2", wf2)

        workflow_status = test_env.workflow_manager.get_workflow_status()

        # Verify status does NOT show wf1 as deleted (it's not in .cec)
        assert "wf1" not in workflow_status.sync_status.deleted, \
            "wf1 should NOT be in sync_status.deleted (never committed to .cec)"

        # ACT: Resolve wf2 (should trigger cleanup of wf1)
        wf2_analysis = next(wf for wf in workflow_status.analyzed_workflows if wf.name == "wf2")
        test_env.workflow_manager.apply_resolution(wf2_analysis.resolution)

        # ASSERT: wf1 should be removed from pyproject even though it was never committed
        config = test_env.pyproject.load()
        workflows = config["tool"]["comfygit"]["workflows"]

        assert "wf1" not in workflows, \
            "BUG: wf1 should be removed from pyproject even though it was never committed"

        assert "wf2" in workflows, \
            "wf2 should exist in pyproject"
