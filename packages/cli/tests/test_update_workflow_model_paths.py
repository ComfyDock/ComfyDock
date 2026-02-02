"""TDD test for update_workflow_model_paths() function.

This test directly tests the workflow_manager.update_workflow_model_paths() method
to verify it correctly updates workflow JSON files with resolved model paths.

The Bug (Reproduced in test_skips_when_resolved_model_is_none):
----------------------------------------------------------------
After running `cg workflow resolve` with interactive downloads:
1. User selects "Download from URL" for missing models
2. Strategy returns ResolvedModel with resolved_model=None (download intent)
3. Models get downloaded and indexed successfully
4. Pyproject.toml gets updated via _update_model_hash()
5. BUT workflow JSON never gets updated with the correct paths!

Root Cause:
-----------
update_workflow_model_paths() skips models where resolved_model=None (line 1250-1252).
Download intents have resolved_model=None, so even after the download completes and
the model is in the index, the workflow JSON doesn't get updated.

Expected Fix:
-------------
After downloads complete, either:
1. Re-resolve the workflow to get updated ResolvedModel objects with actual models
2. Update the ResolutionResult as downloads complete
3. Call update_workflow_model_paths() again with fresh data after downloads

Test Strategy:
--------------
- test_updates_workflow_json_with_resolved_models: Passes (confirms happy path works)
- test_skips_when_resolved_model_is_none: Passes NOW (demonstrates bug), should FAIL after fix
"""

import json

from comfygit_core.models.workflow import (
    ResolutionResult,
    ResolvedModel,
    WorkflowNodeWidgetRef,
)
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.workflow_builder import WorkflowBuilder


class TestUpdateWorkflowModelPaths:
    """Test the update_workflow_model_paths() method directly."""

    def test_updates_workflow_json_with_resolved_models(self, test_env, test_workspace):
        """Test that update_workflow_model_paths() updates the workflow JSON.

        This is the CORE functionality - given a ResolutionResult with resolved models,
        the workflow JSON should be updated with the normalized paths.
        """
        # ARRANGE: Create model in index
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("my_model.safetensors", "checkpoints")
        builder.index_all()

        # Get the model from index
        models = test_workspace.model_repository.get_by_category("checkpoints")
        model = next((m for m in models if m.filename == "my_model.safetensors"), None)
        assert model is not None

        # Create workflow with incorrect path
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("wrong\\path\\my_model.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        workflow_path = test_env.workflow_manager.comfyui_workflows / "test.json"

        # Verify original has wrong path
        with open(workflow_path) as f:
            original = json.load(f)
        assert original["nodes"][0]["widgets_values"][0] == "wrong\\path\\my_model.safetensors"

        # Create ResolutionResult manually with the resolved model
        reference = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="wrong\\path\\my_model.safetensors",
        )

        resolved = ResolvedModel(
            workflow="test",
            reference=reference,
            resolved_model=model,  # Model IS resolved
            model_source=None,
            is_optional=False,
            match_type="exact",
            match_confidence=1.0,
            target_path=None,
            needs_path_sync=True,
        )

        result = ResolutionResult(
            workflow_name="test",
            nodes_resolved=[],
            nodes_unresolved=[],
            nodes_ambiguous=[],
            models_resolved=[resolved],
            models_unresolved=[],
            models_ambiguous=[],
        )

        # ACT: Call update_workflow_model_paths()
        test_env.workflow_manager.update_workflow_model_paths(result)

        # ASSERT: Workflow JSON should be updated
        with open(workflow_path) as f:
            updated = json.load(f)

        updated_path = updated["nodes"][0]["widgets_values"][0]

        # Expected: "my_model.safetensors" (base directory stripped)
        assert updated_path == "my_model.safetensors", (
            f"Workflow JSON not updated! Expected 'my_model.safetensors' but got '{updated_path}'"
        )

        # No backslashes
        assert "\\" not in updated_path

    def test_skips_when_resolved_model_is_none(self, test_env, test_workspace):
        """Test that models with resolved_model=None are skipped (download intent case).

        This demonstrates the BUG: when a model has match_type="download_intent",
        resolved_model is None, so update_workflow_model_paths() skips it even though
        the download may have completed and the model is now in the index!
        """
        # ARRANGE: Create workflow
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("download\\intent\\model.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "bug_test", workflow)

        workflow_path = test_env.workflow_manager.comfyui_workflows / "bug_test.json"

        # Create ResolutionResult with download_intent (resolved_model=None)
        reference = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="download\\intent\\model.safetensors",
        )

        # This is what happens during interactive resolution with downloads!
        resolved = ResolvedModel(
            workflow="bug_test",
            reference=reference,
            resolved_model=None,  # BUG: This is None for download intents!
            model_source="https://example.com/model.safetensors",
            is_optional=False,
            match_type="download_intent",
            match_confidence=1.0,
            target_path=None,
            needs_path_sync=True,
        )

        result = ResolutionResult(
            workflow_name="bug_test",
            nodes_resolved=[],
            nodes_unresolved=[],
            nodes_ambiguous=[],
            models_resolved=[resolved],
            models_unresolved=[],
            models_ambiguous=[],
        )

        # ACT: Call update_workflow_model_paths()
        test_env.workflow_manager.update_workflow_model_paths(result)

        # ASSERT: Workflow JSON is NOT updated (demonstrating the bug)
        with open(workflow_path) as f:
            updated = json.load(f)

        updated_path = updated["nodes"][0]["widgets_values"][0]

        # The BUG: Path is NOT updated because resolved_model is None
        # It still has the original path with backslashes
        assert updated_path == "download\\intent\\model.safetensors", (
            f"Expected bug: path should NOT be updated when resolved_model=None. "
            f"If this fails, the bug might be fixed! Got: '{updated_path}'"
        )
