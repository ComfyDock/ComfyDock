"""Integration tests for workflow deletion cleanup during commit.

Bug Report:
When a user deletes workflows in ComfyUI and commits, the system:
1. ✅ Correctly removes the workflow JSON from .cec/workflows/
2. ❌ FAILS to remove the workflow section from pyproject.toml [tool.comfygit.workflows.NAME]
3. ❌ FAILS to clean up orphaned models from [tool.comfygit.models] that were only in deleted workflows
4. ❌ FAILS to clean up orphaned dependency groups for deleted workflows

This causes:
- Stale pyproject.toml entries referencing non-existent workflows
- False warnings during export about models without sources (from deleted workflows)
- Accumulation of unused dependency groups
- Incorrect status display showing deleted workflows as "deleted" even after commit

The root cause: execute_commit() only processes "new" and "modified" workflows,
completely ignoring "deleted" workflows. It calls copy_all_workflows() which removes
JSON files, but never cleans up the pyproject.toml sections.
"""
import subprocess
import sys
from pathlib import Path

# Add parent dir to path for conftest import
sys.path.insert(0, str(Path(__file__).parent.parent))

from comfygit_core.models.workflow_contract import NamedWorkflowContract, WorkflowExecutionContract
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.pyproject_assertions import PyprojectAssertions
from helpers.workflow_builder import WorkflowBuilder


class TestWorkflowDeletionCleanup:
    """Test that deleting workflows properly cleans up pyproject.toml."""

    def test_delete_workflow_removes_pyproject_section(self, test_env, test_workspace):
        """Test that deleting a workflow removes its pyproject.toml section.

        Scenario:
        1. Create and commit workflow 'default' with resolved models
        2. Create and commit workflow 'secondary' with different models
        3. Delete 'default' workflow in ComfyUI
        4. Commit changes
        5. Expected: [tool.comfygit.workflows.default] should be removed
        6. Current bug: Section remains in pyproject.toml
        """
        # ARRANGE: Create test models
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("model1.safetensors", "checkpoints", size_mb=4)
        builder.add_model("model2.safetensors", "checkpoints", size_mb=4)
        builder.index_all()

        # Create workflow 'default' using model1
        workflow1 = (
            WorkflowBuilder()
            .add_checkpoint_loader("model1.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "default", workflow1)

        # Create workflow 'secondary' using model2
        workflow2 = (
            WorkflowBuilder()
            .add_checkpoint_loader("model2.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "secondary", workflow2)

        # Commit both workflows
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add two workflows")

        # Verify both workflows are in pyproject.toml
        assertions = PyprojectAssertions(test_env)
        assertions.has_workflow("default")
        assertions.has_workflow("secondary")

        # ACT: Delete 'default' workflow (simulate user deleting in ComfyUI)
        default_workflow_path = test_env.comfyui_path / "user" / "default" / "workflows" / "default.json"
        default_workflow_path.unlink()

        # Commit the deletion
        workflow_status = test_env.workflow_manager.get_workflow_status()
        assert "default" in workflow_status.sync_status.deleted, \
            "default should be detected as deleted"

        test_env.execute_commit(workflow_status, message="Delete default workflow")

        # ASSERT: 'default' workflow section should be removed from pyproject.toml
        config = test_env.pyproject.load()
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})

        assert "default" not in workflows, \
            "BUG: Deleted workflow 'default' section should be removed from pyproject.toml"

        assert "secondary" in workflows, \
            "Remaining workflow 'secondary' should still exist"

        # Verify workflow JSON was removed from .cec
        assert not (test_env.cec_path / "workflows" / "default.json").exists(), \
            "Workflow JSON should be removed from .cec"

    def test_delete_workflow_cleans_orphaned_models(self, test_env, test_workspace):
        """Test that deleting a workflow cleans up orphaned models from global table.

        Scenario:
        1. Create workflow 'wf1' with model A
        2. Create workflow 'wf2' with model B
        3. Commit both
        4. Delete 'wf1'
        5. Commit deletion
        6. Expected: Model A removed from [tool.comfygit.models] (orphaned)
        7. Expected: Model B remains (still referenced by wf2)
        8. Current bug: Model A remains in global table
        """
        # ARRANGE: Create models
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("model_a.safetensors", "checkpoints", size_mb=4)
        builder.add_model("model_b.safetensors", "checkpoints", size_mb=4)
        builder.index_all()

        # Create wf1 with model A
        wf1 = WorkflowBuilder().add_checkpoint_loader("model_a.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "wf1", wf1)

        # Create wf2 with model B
        wf2 = WorkflowBuilder().add_checkpoint_loader("model_b.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "wf2", wf2)

        # Commit both
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add wf1 and wf2")

        # Get actual hashes from pyproject after commit
        config = test_env.pyproject.load()
        wf1_models = config.get("tool", {}).get("comfygit", {}).get("workflows", {}).get("wf1", {}).get("models", [])
        wf2_models = config.get("tool", {}).get("comfygit", {}).get("workflows", {}).get("wf2", {}).get("models", [])

        model_a_hash = wf1_models[0]["hash"]
        model_b_hash = wf2_models[0]["hash"]

        # Verify both models in global table
        global_models = config.get("tool", {}).get("comfygit", {}).get("models", {})
        assert model_a_hash in global_models, "Model A should be in global table"
        assert model_b_hash in global_models, "Model B should be in global table"

        # ACT: Delete wf1
        (test_env.comfyui_path / "user" / "default" / "workflows" / "wf1.json").unlink()

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Delete wf1")

        # ASSERT: Model A should be removed (orphaned), Model B should remain
        config = test_env.pyproject.load()
        global_models = config.get("tool", {}).get("comfygit", {}).get("models", {})

        assert model_a_hash not in global_models, \
            "BUG: Orphaned model A should be removed from global table"

        assert model_b_hash in global_models, \
            "Model B should remain (still referenced by wf2)"

    def test_delete_all_workflows_cleans_everything(self, test_env, test_workspace):
        """Test that deleting ALL workflows removes all workflow-related data.

        Scenario:
        1. Create and commit 3 workflows with different models and nodes
        2. Delete ALL workflows
        3. Commit deletion
        4. Expected: All workflow sections removed, all models removed (orphaned), nodes remain
        5. Current bug: Workflow sections and models remain
        """
        # ARRANGE: Create models
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("m1.safetensors", "checkpoints")
        builder.add_model("m2.safetensors", "loras")
        builder.add_model("m3.safetensors", "checkpoints")
        builder.index_all()

        # Create 3 workflows
        for i, model_file in enumerate(["m1.safetensors", "m2.safetensors", "m3.safetensors"], 1):
            if i == 2:
                # Lora for workflow 2
                wf = WorkflowBuilder().add_lora_loader(model_file).build()
            else:
                wf = WorkflowBuilder().add_checkpoint_loader(model_file).build()
            simulate_comfyui_save_workflow(test_env, f"wf{i}", wf)

        # Commit all
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add 3 workflows")

        # Verify all workflows and models exist
        config = test_env.pyproject.load()
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})

        assert len(workflows) == 3, "Should have 3 workflows"
        assert len(models_section) == 3, "Should have 3 models"

        # ACT: Delete ALL workflows
        workflows_path = test_env.comfyui_path / "user" / "default" / "workflows"
        for wf_file in workflows_path.glob("*.json"):
            wf_file.unlink()

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Delete all workflows")

        # ASSERT: Everything should be cleaned
        config = test_env.pyproject.load()
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})

        assert len(workflows) == 0, \
            "BUG: All workflow sections should be removed"

        assert len(models_section) == 0, \
            "BUG: All orphaned models should be removed"

    def test_rename_workflow_via_delete_and_add(self, test_env, test_workspace):
        """Test workflow rename scenario (delete old, add new with same content).

        This is the exact scenario from the bug report where user:
        1. Has 'default' workflow committed
        2. Renames to 'depthflow_showcase_v2' in ComfyUI (appears as delete + add)
        3. Commits
        4. Old 'default' section should be removed
        """
        # ARRANGE: Create and commit 'default' workflow
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("model.safetensors", "checkpoints")
        builder.index_all()

        wf = WorkflowBuilder().add_checkpoint_loader("model.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "default", wf)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add default workflow")

        # Verify 'default' exists and get model hash
        assertions = PyprojectAssertions(test_env)
        assertions.has_workflow("default").has_model_count(1)

        config = test_env.pyproject.load()
        default_models = config.get("tool", {}).get("comfygit", {}).get("workflows", {}).get("default", {}).get("models", [])
        model_hash = default_models[0]["hash"]

        # ACT: Rename workflow (delete old, add new)
        (test_env.comfyui_path / "user" / "default" / "workflows" / "default.json").unlink()
        simulate_comfyui_save_workflow(test_env, "depthflow_showcase_v2", wf)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        assert "default" in workflow_status.sync_status.deleted
        assert "depthflow_showcase_v2" in workflow_status.sync_status.new

        test_env.execute_commit(workflow_status, message="Rename to depthflow_showcase_v2")

        # ASSERT: Old workflow section removed, new one added
        config = test_env.pyproject.load()
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})

        assert "default" not in workflows, \
            "BUG: Old 'default' section should be removed"

        assert "depthflow_showcase_v2" in workflows, \
            "New 'depthflow_showcase_v2' section should exist"

        # Model should still exist (referenced by new workflow)
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})
        assert model_hash in models_section, \
            "Model should remain (referenced by renamed workflow)"

    def test_delete_workflow_removes_execution_contract(self, test_env, test_workspace):
        """Deleting a workflow should remove its nested execution contract."""
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("model.safetensors", "checkpoints")
        builder.index_all()

        wf = WorkflowBuilder().add_checkpoint_loader("model.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "default", wf)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add default workflow")

        contract = WorkflowExecutionContract(
            contracts={"default": NamedWorkflowContract()},
            api_prompt_file="workflow_api/default.api.json",
        )
        test_env.pyproject.workflows.set_execution_contract("default", contract)

        api_prompt = test_env.cec_path / "workflow_api" / "default.api.json"
        api_prompt.parent.mkdir(parents=True, exist_ok=True)
        api_prompt.write_text(
            '{"1": {"class_type": "CheckpointLoaderSimple"}}',
            encoding="utf-8",
        )

        (test_env.comfyui_path / "user" / "default" / "workflows" / "default.json").unlink()

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Delete default workflow")

        config = test_env.pyproject.load()
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})
        assert "default" not in workflows, \
            "Deleted workflow section should be removed with nested execution contract"
        assert not api_prompt.exists(), \
            "Deleted workflow's referenced API prompt artifact should be removed"

    def test_commit_prunes_unreferenced_workflow_api_artifacts(self, test_env, test_workspace):
        """Commit should remove workflow_api files that no contract references."""
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("model.safetensors", "checkpoints")
        builder.index_all()

        wf = WorkflowBuilder().add_checkpoint_loader("model.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "default", wf)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add default workflow")

        api_dir = test_env.cec_path / "workflow_api"
        api_dir.mkdir(parents=True, exist_ok=True)
        referenced_api = api_dir / "default.api.json"
        orphaned_api = api_dir / "orphaned.api.json"
        referenced_api.write_text(
            '{"1": {"class_type": "CheckpointLoaderSimple"}}',
            encoding="utf-8",
        )
        orphaned_api.write_text('{"1": {"class_type": "SaveImage"}}', encoding="utf-8")

        contract = WorkflowExecutionContract(
            contracts={"default": NamedWorkflowContract()},
            api_prompt_file="workflow_api/default.api.json",
        )
        test_env.pyproject.workflows.set_execution_contract("default", contract)

        subprocess.run(
            ["git", "add", "pyproject.toml", "workflow_api"],
            cwd=test_env.cec_path,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add execution contract and orphan API prompt"],
            cwd=test_env.cec_path,
            check=True,
        )

        assert referenced_api.exists()
        assert orphaned_api.exists()

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Clean orphan workflow API prompt")

        assert referenced_api.exists(), "Referenced API prompt artifact should remain"
        assert not orphaned_api.exists(), "Unreferenced API prompt artifact should be removed"

        tracked_files = subprocess.run(
            ["git", "ls-files", "workflow_api"],
            cwd=test_env.cec_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        assert "workflow_api/default.api.json" in tracked_files
        assert "workflow_api/orphaned.api.json" not in tracked_files

    def test_rename_workflow_drops_old_execution_contract(self, test_env, test_workspace):
        """Rename should follow delete-plus-create semantics for contracts."""
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("model.safetensors", "checkpoints")
        builder.index_all()

        wf = WorkflowBuilder().add_checkpoint_loader("model.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "default", wf)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add default workflow")

        contract = WorkflowExecutionContract(
            contracts={"default": NamedWorkflowContract(display_name="Default")},
        )
        test_env.pyproject.workflows.set_execution_contract("default", contract)

        (test_env.comfyui_path / "user" / "default" / "workflows" / "default.json").unlink()
        simulate_comfyui_save_workflow(test_env, "depthflow_showcase_v2", wf)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Rename to depthflow_showcase_v2")

        config = test_env.pyproject.load()
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})

        assert "default" not in workflows, "Old workflow entry should be removed"
        assert "depthflow_showcase_v2" in workflows, "Renamed workflow should exist"
        assert "execution_contract" not in workflows["depthflow_showcase_v2"], \
            "Rename should not preserve workflow-scoped execution contract in first slice"

    def test_export_after_workflow_deletion_no_false_warnings(self, test_env, test_workspace):
        """Test that export doesn't warn about models from deleted workflows.

        This tests the exact bug from the report:
        1. Commit workflow with models (no sources added)
        2. Delete workflow and commit
        3. Check pyproject.toml
        4. Expected: No models remain (cleaned up)
        5. Current bug: Models remain without sources
        """
        # ARRANGE: Create workflow with models (no sources)
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("m1.safetensors", "checkpoints")
        builder.add_model("m2.safetensors", "loras")
        builder.index_all()

        wf = (
            WorkflowBuilder()
            .add_checkpoint_loader("m1.safetensors")
            .add_lora_loader("m2.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "temp_workflow", wf)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add temp workflow")

        # Verify models exist
        config = test_env.pyproject.load()
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})
        assert len(models_section) == 2, "Should have 2 models after initial commit"

        # Delete workflow
        (test_env.comfyui_path / "user" / "default" / "workflows" / "temp_workflow.json").unlink()

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Delete temp workflow")

        # ASSERT: No models should remain (they were cleaned up)
        config = test_env.pyproject.load()
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})
        assert len(models_section) == 0, \
            "BUG: No models should remain after workflow deletion (orphaned models cleaned up)"

    def test_multiple_deletes_and_adds_in_single_commit(self, test_env, test_workspace):
        """Test complex scenario: delete some workflows, add others, modify one.

        Scenario mimicking real usage:
        1. Have workflows A, B, C committed
        2. Delete A
        3. Modify B
        4. Add D
        5. Commit
        6. Expected: A removed, B updated, C unchanged, D added
        """
        # ARRANGE: Create models
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("ma.safetensors", "checkpoints")
        builder.add_model("mb.safetensors", "checkpoints")
        builder.add_model("mc.safetensors", "checkpoints")
        builder.add_model("md.safetensors", "loras")  # Use loras category for the lora model
        builder.index_all()

        # Create workflows A, B, C
        for name, model in [("wf_a", "ma.safetensors"), ("wf_b", "mb.safetensors"), ("wf_c", "mc.safetensors")]:
            wf = WorkflowBuilder().add_checkpoint_loader(model).build()
            simulate_comfyui_save_workflow(test_env, name, wf)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add A, B, C")

        # Get model hashes after initial commit
        config = test_env.pyproject.load()
        wf_a_models = config.get("tool", {}).get("comfygit", {}).get("workflows", {}).get("wf_a", {}).get("models", [])
        ma_hash = wf_a_models[0]["hash"]

        # ACT: Complex changes
        # Delete A
        (test_env.comfyui_path / "user" / "default" / "workflows" / "wf_a.json").unlink()

        # Modify B (add a lora)
        wf_b_modified = (
            WorkflowBuilder()
            .add_checkpoint_loader("mb.safetensors")
            .add_lora_loader("md.safetensors")  # md.safetensors is now a lora
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "wf_b", wf_b_modified)

        # Add D (uses md.safetensors as a lora since that's what we created)
        wf_d = WorkflowBuilder().add_lora_loader("md.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "wf_d", wf_d)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Delete A, modify B, add D")

        # ASSERT: Verify final state
        config = test_env.pyproject.load()
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})

        assert "wf_a" not in workflows, \
            "BUG: Deleted workflow A should be removed"

        assert "wf_b" in workflows, "Modified workflow B should exist"
        assert "wf_c" in workflows, "Unchanged workflow C should exist"
        assert "wf_d" in workflows, "New workflow D should exist"

        # Model A should be orphaned and removed
        assert ma_hash not in models_section, \
            "BUG: Model A should be removed (only used by deleted wf_a)"

        # Models B, C, D should remain (we just verify count > 0 since models are shared)
        assert len(models_section) >= 2, \
            "Should have at least 2 models remaining (B, C, and possibly D)"

    def test_resolved_but_never_committed_workflow_cleanup(self, test_env, test_workspace):
        """Test that resolved-but-never-committed workflows are cleaned up on commit.

        Edge case scenario:
        1. Create workflow 'temp_wf' in ComfyUI
        2. Run 'resolve' on it (adds to pyproject.toml but NOT to .cec)
        3. Delete workflow file in ComfyUI (without ever committing)
        4. Commit (with or without other workflows)
        5. Expected: 'temp_wf' section should be removed from pyproject.toml
        6. Bug: Section remains as orphan since it was never in .cec

        Root cause: sync_status.deleted only detects workflows in .cec but not ComfyUI.
        Workflows that are only in pyproject.toml become orphans.
        """
        # ARRANGE: Create models for both workflows
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("model1.safetensors", "checkpoints", size_mb=4)
        builder.add_model("model2.safetensors", "checkpoints", size_mb=4)
        builder.index_all()

        # Create and COMMIT workflow 'committed_wf' (this one will stay)
        committed_wf = WorkflowBuilder().add_checkpoint_loader("model1.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "committed_wf", committed_wf)
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add committed workflow")

        # Verify committed_wf is now in .cec
        assert (test_env.cec_path / "workflows" / "committed_wf.json").exists()

        # Create 'temp_wf' and RESOLVE it (adds to pyproject) but DO NOT commit
        temp_wf = WorkflowBuilder().add_checkpoint_loader("model2.safetensors").build()
        simulate_comfyui_save_workflow(test_env, "temp_wf", temp_wf)

        # Resolve temp_wf - this adds it to pyproject.toml
        deps, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("temp_wf")
        test_env.workflow_manager.apply_resolution(resolution)

        # Verify temp_wf is in pyproject but NOT in .cec
        config = test_env.pyproject.load()
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})
        assert "temp_wf" in workflows, "temp_wf should be in pyproject after resolve"
        assert not (test_env.cec_path / "workflows" / "temp_wf.json").exists(), \
            "temp_wf should NOT be in .cec (never committed)"

        # Get the model hash for temp_wf to verify cleanup
        temp_wf_models = workflows.get("temp_wf", {}).get("models", [])
        temp_model_hash = temp_wf_models[0]["hash"] if temp_wf_models else None

        # ACT: Delete temp_wf from ComfyUI (simulate user deleting it)
        (test_env.comfyui_path / "user" / "default" / "workflows" / "temp_wf.json").unlink()

        # Commit - this should clean up the orphaned temp_wf from pyproject
        workflow_status = test_env.workflow_manager.get_workflow_status()

        # Verify temp_wf is NOT in deleted list (since it was never in .cec)
        assert "temp_wf" not in workflow_status.sync_status.deleted, \
            "temp_wf should not be detected as deleted (never in .cec)"

        test_env.execute_commit(workflow_status, message="Commit after deleting temp_wf")

        # ASSERT: temp_wf should be cleaned from pyproject.toml
        config = test_env.pyproject.load()
        workflows = config.get("tool", {}).get("comfygit", {}).get("workflows", {})

        assert "temp_wf" not in workflows, \
            "BUG: Resolved-but-never-committed workflow 'temp_wf' should be removed from pyproject"

        assert "committed_wf" in workflows, \
            "committed_wf should remain in pyproject"

        # Verify orphaned model is also cleaned up
        models_section = config.get("tool", {}).get("comfygit", {}).get("models", {})
        if temp_model_hash:
            assert temp_model_hash not in models_section, \
                "BUG: Model from deleted workflow should be cleaned up"
