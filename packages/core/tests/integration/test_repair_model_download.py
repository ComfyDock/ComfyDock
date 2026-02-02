"""Integration tests for model download support in repair command.

This test suite follows TDD - tests are written first to validate the expected
behavior before implementation.
"""

# Import helpers using sys.path manipulation
import sys
from pathlib import Path

from conftest import simulate_comfyui_save_workflow

sys.path.insert(0, str(Path(__file__).parent.parent))
from helpers.model_index_builder import ModelIndexBuilder
from helpers.workflow_builder import WorkflowBuilder


class TestRepairModelDownload:
    """Test repair command detects and downloads missing models."""

    def test_status_detects_missing_models_after_git_pull(self, test_env, test_workspace):
        """When models exist in pyproject but not locally, status should detect them."""
        # ARRANGE: Create a workflow with a model that's indexed, then remove it to simulate git pull
        # Note: We don't use test_models fixture to avoid model conflicts
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model(
            filename="flux_dev.safetensors",
            relative_path="checkpoints",
            size_mb=4,
            category="checkpoints"
        )
        builder.index_all()

        # Create and resolve workflow
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("flux_dev.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)
        test_env.resolve_workflow(name="test_workflow", fix=True)

        # Commit workflow
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add workflow with model")

        # Simulate git pull scenario: model is in pyproject but not in local index
        # Remove model from filesystem and re-scan
        model_path = test_workspace.paths.models / "checkpoints/flux_dev.safetensors"
        if model_path.exists():
            model_path.unlink()
        test_workspace.sync_model_directory()

        # ACT: Get status
        status = test_env.status()

        # ASSERT: Should detect missing model
        assert hasattr(status, 'missing_models'), "EnvironmentStatus should have missing_models field"
        assert len(status.missing_models) > 0, "Should detect at least one missing model"

        missing = status.missing_models[0]
        assert hasattr(missing, 'model'), "MissingModelInfo should have model field"
        assert hasattr(missing, 'workflow_names'), "MissingModelInfo should have workflow_names field"
        assert hasattr(missing, 'criticality'), "MissingModelInfo should have criticality field"
        assert hasattr(missing, 'can_download'), "MissingModelInfo should have can_download field"

        assert missing.model.filename == "flux_dev.safetensors"
        assert "test_workflow" in missing.workflow_names
        assert not status.is_synced, "Environment should not be synced with missing models"

    def test_sync_preview_includes_missing_models(self, test_env, test_workspace):
        """Sync preview should show downloadable and unavailable models."""
        # ARRANGE: Similar setup with missing model
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model(
            filename="test_model.safetensors",
            relative_path="checkpoints",
            size_mb=4,
            category="checkpoints"
        )
        builder.index_all()

        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("test_model.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test_wf", workflow)
        test_env.resolve_workflow(name="test_wf", fix=True)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add workflow")

        # Remove model
        model_path = test_workspace.paths.models / "checkpoints/test_model.safetensors"
        if model_path.exists():
            model_path.unlink()
        test_workspace.sync_model_directory()

        # ACT: Get sync preview
        status = test_env.status()
        preview = status.get_sync_preview()

        # ASSERT: Preview should include model information
        assert 'models_missing' in preview, "Preview should include models_missing"
        assert 'models_downloadable' in preview, "Preview should include models_downloadable"
        assert 'models_unavailable' in preview, "Preview should include models_unavailable"
        assert len(preview['models_missing']) > 0, "Should show missing models"

    def test_sync_result_has_model_tracking_fields(self, test_env):
        """SyncResult should have fields for tracking model downloads."""
        # ACT: Call sync
        sync_result = test_env.sync()

        # ASSERT: Should have model tracking fields
        assert hasattr(sync_result, 'models_downloaded'), "SyncResult should have models_downloaded field"
        assert hasattr(sync_result, 'models_failed'), "SyncResult should have models_failed field"
        assert isinstance(sync_result.models_downloaded, list), "models_downloaded should be a list"
        assert isinstance(sync_result.models_failed, list), "models_failed should be a list"

    def test_sync_accepts_model_strategy_parameter(self, test_env):
        """Sync should accept model_strategy and model_callbacks parameters."""
        # ACT & ASSERT: Sync should accept new parameters without error
        from comfygit_core.models.workflow import BatchDownloadCallbacks

        model_callbacks = BatchDownloadCallbacks()

        # Should not raise TypeError about unexpected parameters
        sync_result = test_env.sync(model_strategy="skip", model_callbacks=model_callbacks)
        assert sync_result.success, "Sync should succeed with new parameters"

    def test_missing_models_deduplication_across_workflows(self, test_env, test_workspace):
        """Same model used in multiple workflows should only appear once in missing list."""
        # ARRANGE: Create same model used in two workflows
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model(
            filename="shared_model.safetensors",
            relative_path="checkpoints",
            size_mb=4,
            category="checkpoints"
        )
        builder.index_all()

        # Create two workflows using the same model
        workflow1 = (
            WorkflowBuilder()
            .add_checkpoint_loader("shared_model.safetensors")
            .build()
        )
        workflow2 = (
            WorkflowBuilder()
            .add_checkpoint_loader("shared_model.safetensors")
            .build()
        )

        simulate_comfyui_save_workflow(test_env, "workflow1", workflow1)
        simulate_comfyui_save_workflow(test_env, "workflow2", workflow2)

        test_env.resolve_workflow(name="workflow1", fix=True)
        test_env.resolve_workflow(name="workflow2", fix=True)

        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_env.execute_commit(workflow_status, message="Add workflows")

        # Remove model
        model_path = test_workspace.paths.models / "checkpoints/shared_model.safetensors"
        if model_path.exists():
            model_path.unlink()
        test_workspace.sync_model_directory()

        # ACT: Get status
        status = test_env.status()

        # ASSERT: Should show one missing model with both workflows listed
        assert len(status.missing_models) == 1, "Should deduplicate model by hash"
        missing = status.missing_models[0]
        assert len(missing.workflow_names) == 2, "Should track both workflows"
        assert "workflow1" in missing.workflow_names
        assert "workflow2" in missing.workflow_names
