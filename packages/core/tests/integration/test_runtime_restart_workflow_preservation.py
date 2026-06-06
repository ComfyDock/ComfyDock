"""Integration tests for runtime restart workflow preservation.

When users install custom nodes via the in-UI manager and trigger a restart
(exit code 42), uncommitted workflow edits should be preserved. The restart
only needs to sync Python dependencies, not restore workflows from .cec.
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


class TestRuntimeRestartPreservesWorkflows:
    """Test that runtime restart syncs preserve uncommitted workflows."""

    def test_capture_workflow_records_saved_workflow_as_working_snapshot(self, test_env):
        """capture_workflow() should copy one saved workflow and ensure manifest path."""
        workflow = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "captured_workflow", workflow)

        tracked_path = test_env.capture_workflow("captured_workflow.json")

        assert tracked_path == test_env.cec_path / "workflows" / "captured_workflow.json"
        assert tracked_path.exists()
        assert json.loads(tracked_path.read_text()) == workflow

        snapshot = test_env.get_manifest_snapshot()
        assert snapshot.workflows["captured_workflow"].path == (
            "workflows/captured_workflow.json"
        )

    def test_sync_with_preserve_workflows_keeps_uncommitted_edits(self, test_env):
        """sync(preserve_workflows=True) should preserve uncommitted workflow edits.

        Scenario: User makes workflow edits, installs custom node via UI, hits restart.
        The restart should update Python deps but NOT nuke uncommitted workflows.
        """
        # ARRANGE: Create uncommitted workflow (simulating user edits in UI)
        workflow = create_simple_workflow()
        workflow["1"]["inputs"]["ckpt_name"] = "my_custom_model.safetensors"  # User edit
        save_workflow_to_comfyui(test_env, "my_workflow", workflow)

        wf_path = test_env.comfyui_path / "user" / "default" / "workflows" / "my_workflow.json"
        assert wf_path.exists(), "Workflow should exist in ComfyUI"

        # Verify uncommitted
        status = test_env.status()
        assert "my_workflow" in status.workflow.sync_status.new, "Workflow should be uncommitted"

        # ACT: Run sync with preserve_workflows=True (simulating restart after node install)
        result = test_env.sync(preserve_workflows=True)

        # ASSERT: Workflow still exists with same content
        assert result.success, "Sync should succeed"
        assert wf_path.exists(), "Uncommitted workflow should be preserved"

        with open(wf_path) as f:
            preserved_workflow = json.load(f)
        assert preserved_workflow == workflow, "Workflow edits should be preserved"

        # Still uncommitted
        status = test_env.status()
        assert "my_workflow" in status.workflow.sync_status.new

    def test_sync_with_preserve_workflows_false_deletes_uncommitted(self, test_env):
        """sync(preserve_workflows=False) should delete uncommitted workflows (current behavior).

        This is for operations like git checkout/pull/repair where you want full sync.
        """
        # ARRANGE: Create uncommitted workflow
        workflow = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "uncommitted", workflow)

        wf_path = test_env.comfyui_path / "user" / "default" / "workflows" / "uncommitted.json"
        assert wf_path.exists()

        # ACT: Run sync with preserve_workflows=False (default - full sync)
        result = test_env.sync(preserve_workflows=False)

        # ASSERT: Uncommitted workflow deleted
        assert result.success
        assert not wf_path.exists(), "Uncommitted workflow should be deleted in full sync"

    def test_sync_default_behavior_deletes_uncommitted(self, test_env):
        """sync() without parameters should delete uncommitted (backward compatible).

        Default should remain False for safety - only runtime restart uses True.
        """
        # ARRANGE: Create uncommitted workflow
        workflow = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "uncommitted", workflow)

        wf_path = test_env.comfyui_path / "user" / "default" / "workflows" / "uncommitted.json"
        assert wf_path.exists()

        # ACT: Run sync without parameters (default behavior)
        result = test_env.sync()

        # ASSERT: Uncommitted workflow deleted (preserve_workflows defaults to False)
        assert result.success
        assert not wf_path.exists(), "Default sync should delete uncommitted workflows"

    def test_preserve_workflows_skips_all_workflow_operations(self, test_env):
        """preserve_workflows=True skips ALL workflow restoration operations.

        For runtime restart, we want to leave workflows completely untouched.
        Committed workflows are only restored during full sync (preserve_workflows=False).
        """
        # ARRANGE: Create workflow in .cec (simulating git pull)
        cec_workflows_dir = test_env.cec_path / "workflows"
        cec_workflows_dir.mkdir(parents=True, exist_ok=True)

        workflow = create_simple_workflow()
        cec_wf_path = cec_workflows_dir / "pulled_workflow.json"
        with open(cec_wf_path, 'w') as f:
            json.dump(workflow, f)

        # Commit it
        test_env.git_manager.commit_all("Add pulled_workflow")

        # Verify NOT in ComfyUI yet
        comfyui_wf_path = test_env.comfyui_path / "user" / "default" / "workflows" / "pulled_workflow.json"
        assert not comfyui_wf_path.exists(), "Workflow not in ComfyUI yet"

        # Also create uncommitted workflow
        uncommitted = create_simple_workflow()
        save_workflow_to_comfyui(test_env, "uncommitted", uncommitted)
        uncommitted_path = test_env.comfyui_path / "user" / "default" / "workflows" / "uncommitted.json"
        assert uncommitted_path.exists()

        # ACT: Sync with preserve_workflows=True (runtime restart)
        result = test_env.sync(preserve_workflows=True)

        # ASSERT: Neither workflow touched - all workflow operations skipped
        assert result.success
        assert not comfyui_wf_path.exists(), "preserve_workflows=True skips restoration"
        assert uncommitted_path.exists(), "Uncommitted workflow left untouched"

        # Now do full sync (preserve_workflows=False) to restore committed
        result = test_env.sync(preserve_workflows=False)
        assert result.success
        assert comfyui_wf_path.exists(), "Full sync restores committed workflows"
        assert not uncommitted_path.exists(), "Full sync removes uncommitted workflows"

    def test_preserve_workflows_skips_model_downloads_by_default(self, test_env):
        """Runtime restart should not trigger model downloads (model_strategy defaults to 'skip')."""
        # ARRANGE: Create workflow with missing model in pyproject
        fake_hash = "abc123def456"
        config = test_env.pyproject.load()
        config["tool"]["comfygit"]["models"] = {
            fake_hash: {
                "filename": "missing.safetensors",
                "hash": fake_hash,
                "size": 4 * 1024 * 1024,
                "relative_path": "checkpoints/missing.safetensors",
                "category": "checkpoints",
                "sources": ["https://example.com/missing.safetensors"]
            }
        }
        config["tool"]["comfygit"]["workflows"] = {
            "test_workflow": {
                "models": [
                    {
                        "filename": "missing.safetensors",
                        "hash": fake_hash,
                        "status": "resolved",
                        "criticality": "flexible",
                        "category": "checkpoints",
                        "nodes": []
                    }
                ]
            }
        }
        test_env.pyproject.save(config)

        # ACT: Sync with preserve_workflows=True (runtime restart)
        # Should NOT download models (model_strategy defaults to "skip")
        result = test_env.sync(preserve_workflows=True)

        # ASSERT: No models downloaded
        assert result.success
        assert len(result.models_downloaded) == 0, "Should not download models during runtime restart"
        assert len(result.models_failed) == 0, "Should not attempt model downloads"
