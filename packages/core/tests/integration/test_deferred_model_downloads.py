"""Integration tests for deferred model downloads feature.

Tests the complete flow of collecting download intents during interactive resolution
and executing batch downloads at the end.
"""
from pathlib import Path
from unittest.mock import Mock

import pytest

from comfygit_core.models.workflow import BatchDownloadCallbacks, ResolvedModel
from comfygit_core.strategies.auto import AutoModelStrategy
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.pyproject_assertions import PyprojectAssertions
from helpers.workflow_builder import WorkflowBuilder


class TestDeferredModelDownloads:
    """Test deferred model download functionality."""

    def test_download_intent_stored_in_pyproject(self, test_env):
        """Test that download intent is written to pyproject with sources and relative_path."""
        # ARRANGE - Create workflow with missing model
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("missing_model.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # Create mock strategy that returns download intent
        mock_strategy = Mock()
        target_path = Path("checkpoints/sdxl/missing_model.safetensors")
        download_url = "https://civitai.com/api/download/models/123456"

        mock_strategy.resolve_model = Mock(return_value=ResolvedModel(
            workflow="test",
            reference=Mock(
                node_id="1",
                node_type="CheckpointLoaderSimple",
                widget_index=0,
                widget_value="missing_model.safetensors"
            ),
            resolved_model=None,
            model_source=download_url,
            is_optional=False,
            match_type="download_intent",
            target_path=target_path
        ))

        # ACT - Resolve workflow with download intent
        result = test_env.resolve_workflow(
            name="test",
            model_strategy=mock_strategy,
            fix=True
        )

        # ASSERT - Download intent should be stored in pyproject
        assertions = PyprojectAssertions(test_env)

        # Verify workflow model has download intent fields
        workflow_models = test_env.pyproject.workflows.get_workflow_models("test")
        assert len(workflow_models) == 1, "Should have one workflow model"

        model = workflow_models[0]
        assert model.status == "unresolved", "Status should be unresolved (no hash yet)"
        assert model.sources == [download_url], "Should store download URL in sources"
        assert model.relative_path == target_path.as_posix(), "Should store target path"
        assert model.hash is None, "Hash should be None until downloaded"

    def test_download_intent_resume_after_interrupt(self, test_env):
        """Test that download intents are detected on resume and don't re-prompt."""
        # ARRANGE - Create workflow with download intent already in pyproject
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("model.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # Manually add download intent to pyproject (simulating previous interrupted session)
        from comfygit_core.models.manifest import ManifestWorkflowModel
        from comfygit_core.models.workflow import WorkflowNodeWidgetRef

        download_intent = ManifestWorkflowModel(
            filename="model.safetensors",
            category="checkpoints",
            criticality="flexible",
            status="unresolved",
            nodes=[WorkflowNodeWidgetRef(
                node_id="1",
                node_type="CheckpointLoaderSimple",
                widget_index=0,
                widget_value="model.safetensors"
            )],
            sources=["https://civitai.com/api/download/models/999"],
            relative_path="checkpoints/model.safetensors"
        )
        test_env.pyproject.workflows.add_workflow_model("test", download_intent)

        # Create mock strategy that should NOT be called (intent should be auto-resolved)
        mock_strategy = Mock()
        mock_strategy.resolve_model = Mock(side_effect=AssertionError("Should not prompt user"))

        # ACT - Resolve workflow again
        result = test_env.resolve_workflow(
            name="test",
            model_strategy=mock_strategy,
            fix=True
        )

        # ASSERT - Should detect existing download intent without calling strategy
        assert len(result.models_resolved) > 0, "Should have resolved models"

        # Find the download intent resolution
        download_intents = [m for m in result.models_resolved if m.match_type == "download_intent"]
        assert len(download_intents) == 1, "Should detect one download intent"
        assert download_intents[0].model_source == "https://civitai.com/api/download/models/999"

    def test_batch_download_execution_with_callbacks(self, test_env, test_workspace):
        """Test batch download execution calls all callbacks correctly."""
        # ARRANGE - Create model index builder
        builder = ModelIndexBuilder(test_workspace)

        # Create workflow with missing model
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("test_model.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # Create mock callbacks
        callbacks = BatchDownloadCallbacks(
            on_batch_start=Mock(),
            on_file_start=Mock(),
            on_file_progress=Mock(),
            on_file_complete=Mock(),
            on_batch_complete=Mock()
        )

        # Mock strategy that returns download intent
        mock_strategy = Mock()
        target_path = Path("checkpoints/test_model.safetensors")

        # Create a test file to "download" (simulating successful download)
        full_target_path = test_env.workspace_paths.models / target_path
        full_target_path.parent.mkdir(parents=True, exist_ok=True)
        full_target_path.write_bytes(b"fake model data")

        mock_strategy.resolve_model = Mock(return_value=ResolvedModel(
            workflow="test",
            reference=Mock(
                node_id="1",
                node_type="CheckpointLoaderSimple",
                widget_index=0,
                widget_value="test_model.safetensors"
            ),
            resolved_model=None,
            model_source="https://example.com/model.safetensors",
            is_optional=False,
            match_type="download_intent",
            target_path=target_path
        ))

        # ACT - Resolve with callbacks
        result = test_env.resolve_workflow(
            name="test",
            model_strategy=mock_strategy,
            fix=True,
            download_callbacks=callbacks
        )

        # ASSERT - All callbacks should be called
        callbacks.on_batch_start.assert_called_once_with(1)  # 1 file to download
        callbacks.on_file_start.assert_called_once()  # File started
        callbacks.on_file_complete.assert_called_once()  # File completed
        callbacks.on_batch_complete.assert_called_once()  # Batch done

    def test_batch_download_updates_hash_after_download(self, test_env):
        """Test that pyproject is updated with actual hash after download completes."""
        # This test will fail initially because batch download logic doesn't exist yet
        pytest.skip("TODO: Implement after batch download execution is in place")

    def test_multiple_download_intents_batch_execution(self, test_env):
        """Test multiple download intents are batched together."""
        # This test will fail initially
        pytest.skip("TODO: Implement after batch download execution is in place")

    def test_download_deduplication_by_url(self, test_env):
        """Test that same URL downloads once and reuses model across workflows."""
        # This test will fail initially
        pytest.skip("TODO: Implement after batch download execution is in place")

    def test_download_intent_preserved_across_resolution_sessions(self, test_env):
        """Test that download intents persist when running resolve again.

        Regression test for critical bug where download intents from previous
        sessions were lost when running resolve again to handle other models.

        Scenario:
        1. User queues download for Model A
        2. Model A written to pyproject with sources + relative_path
        3. User runs resolve again (to handle Model B or interrupts)
        4. Download intent for Model A should be preserved in pyproject
        """
        from unittest.mock import patch

        # ARRANGE - Create workflow with 2 missing models
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("model_a.safetensors")
            .add_lora_loader("model_b.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # SESSION 1: Queue download for Model A
        download_url_a = "https://civitai.com/api/download/models/111"
        target_path_a = Path("checkpoints/model_a.safetensors")

        mock_strategy_session1 = Mock()
        mock_strategy_session1.resolve_model = Mock(
            side_effect=[
                # Model A: Return download intent
                ResolvedModel(
                    workflow="test",
                    reference=Mock(
                        node_id="1",
                        node_type="CheckpointLoaderSimple",
                        widget_index=0,
                        widget_value="model_a.safetensors"
                    ),
                    resolved_model=None,
                    model_source=download_url_a,
                    is_optional=False,
                    match_type="download_intent",
                    target_path=target_path_a
                ),
                # Model B: Return None (user skips)
                None
            ]
        )

        # Mock execute_pending_downloads to prevent actual HTTP requests to fake URLs
        with patch.object(test_env.workflow_manager, 'execute_pending_downloads', return_value=[]):
            result1 = test_env.resolve_workflow(
                name="test",
                model_strategy=mock_strategy_session1,
                fix=True
            )

        # ASSERT 1: Model A download intent written to pyproject
        workflow_models = test_env.pyproject.workflows.get_workflow_models("test")
        model_a = next((m for m in workflow_models if m.filename == "model_a.safetensors"), None)
        assert model_a is not None, "Model A should be in pyproject"
        assert model_a.status == "unresolved"
        assert model_a.sources == [download_url_a], "Model A should have download URL"
        assert model_a.relative_path == target_path_a.as_posix(), "Model A should have target path"

        # ASSERT 2: Model B is unresolved (no sources)
        model_b = next((m for m in workflow_models if m.filename == "model_b.safetensors"), None)
        assert model_b is not None, "Model B should be in pyproject"
        assert model_b.status == "unresolved"
        assert model_b.sources == [], "Model B should have no sources"

        # SESSION 2: Run resolve again to handle Model B
        download_url_b = "https://civitai.com/api/download/models/222"
        target_path_b = Path("loras/model_b.safetensors")

        mock_strategy_session2 = Mock()
        mock_strategy_session2.resolve_model = Mock(
            return_value=ResolvedModel(
                workflow="test",
                reference=Mock(
                    node_id="2",
                    node_type="LoraLoader",
                    widget_index=0,
                    widget_value="model_b.safetensors"
                ),
                resolved_model=None,
                model_source=download_url_b,
                is_optional=False,
                match_type="download_intent",
                target_path=target_path_b
            )
        )

        with patch.object(test_env.workflow_manager, 'execute_pending_downloads', return_value=[]):
            result2 = test_env.resolve_workflow(
                name="test",
                model_strategy=mock_strategy_session2,
                fix=True
            )

        # CRITICAL ASSERTION: Model A download intent should still be preserved!
        workflow_models_after = test_env.pyproject.workflows.get_workflow_models("test")
        assert len(workflow_models_after) == 2, "Should have 2 models in pyproject"

        model_a_after = next((m for m in workflow_models_after if m.filename == "model_a.safetensors"), None)
        assert model_a_after is not None, "Model A should still be in pyproject"
        assert model_a_after.sources == [download_url_a], "Model A download URL should be preserved"
        assert model_a_after.relative_path == target_path_a.as_posix(), "Model A target path should be preserved"
        assert model_a_after.status == "unresolved", "Model A should still be unresolved"

        model_b_after = next((m for m in workflow_models_after if m.filename == "model_b.safetensors"), None)
        assert model_b_after is not None, "Model B should be in pyproject"
        assert model_b_after.sources == [download_url_b], "Model B should have download URL"
        assert model_b_after.relative_path == target_path_b.as_posix(), "Model B should have target path"

        # ASSERT: Both should appear as download intents
        download_intents = [m for m in result2.models_resolved if m.match_type == "download_intent"]
        assert len(download_intents) == 2, "Should detect 2 download intents"

    def test_interrupted_resolution_shows_as_unresolved(self, test_env):
        """Test that models written during interrupted resolution show as unresolved, not optional.

        Regression test for bug where interrupting workflow resolve caused models to be
        incorrectly treated as optional, hiding them from status display.

        Scenario:
        1. User runs workflow resolve
        2. apply_resolution() writes models as status="unresolved", criticality="flexible"
        3. User interrupts (Ctrl+C) before making choices
        4. Next status check should show models as unresolved (not optional)
        """
        import os
        import time

        # ARRANGE - Create workflow with missing models
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("missing_model_1.safetensors")
            .add_lora_loader("missing_model_2.safetensors")
            .build()
        )

        # Save workflow to ComfyUI directory
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # Record workflow file modification time before resolve
        workflow_path = test_env.workflow_manager.comfyui_workflows / "test.json"
        original_mtime = os.path.getmtime(workflow_path)
        time.sleep(0.01)  # Ensure time difference if file gets modified

        # Create a strategy that returns None (simulates user skipping/interrupting)
        skip_strategy = Mock()
        skip_strategy.resolve_model = Mock(return_value=None)

        # ACT - Run resolve with skip strategy (simulates interrupted resolution)
        # This will call apply_resolution() which writes unresolved models to pyproject
        result = test_env.resolve_workflow(
            name="test",
            model_strategy=skip_strategy,
            fix=True
        )

        # ASSERT 1: Models should be in models_unresolved, not models_resolved
        assert len(result.models_unresolved) == 2, "Should have 2 unresolved models"
        assert len(result.models_resolved) == 0, "Should have no resolved models"

        # ASSERT 2: Verify models in pyproject have correct state
        workflow_models = test_env.pyproject.workflows.get_workflow_models("test")
        assert len(workflow_models) == 2, "Should have 2 models in pyproject"

        for model in workflow_models:
            assert model.status == "unresolved", "Models should be unresolved"
            assert model.criticality == "flexible", "Should have flexible criticality (not optional)"
            assert model.hash is None, "Should have no hash"
            assert model.sources == [], "Should have no sources"

        # ASSERT 3: Next resolution should still show as unresolved (not treat as optional)
        result2 = test_env.resolve_workflow(
            name="test",
            model_strategy=skip_strategy,
            fix=True
        )

        assert len(result2.models_unresolved) == 2, "Should still show 2 unresolved models"
        assert len(result2.models_resolved) == 0, "Should not treat as resolved/optional"

        # ASSERT 4: Workflow file should NOT have been modified (no actual path updates)
        new_mtime = os.path.getmtime(workflow_path)
        assert new_mtime == original_mtime, "Workflow file should not be modified when no paths updated"

        # ASSERT 5: Verify has_issues returns True
        assert result2.has_issues is True, "Should have issues (unresolved models)"


class TestModelResolutionContextChanges:
    """Test changes to ModelResolutionContext to support full ManifestWorkflowModel storage."""

    def test_context_stores_full_manifest_model(self, test_env, test_workspace):
        """Test that context.previous_resolutions stores full ManifestWorkflowModel."""
        # ARRANGE - Create workflow with resolved model
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model("test.safetensors", "checkpoints", size_mb=4)
        builder.index_all()

        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("test.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # Resolve once to populate pyproject
        result = test_env.resolve_workflow(
            name="test",
            model_strategy=AutoModelStrategy(),
            fix=True
        )

        # ACT - Resolve again to trigger context resolution
        # The second resolution should detect the previous resolution from pyproject
        result2 = test_env.resolve_workflow(
            name="test",
            model_strategy=AutoModelStrategy(),
            fix=True
        )

        # ASSERT - The second resolution should have detected the resolved model from context
        # This validates that context is being built with full ManifestWorkflowModel objects
        assert len(result2.models_resolved) > 0, "Should have resolved models from context"

        # Verify the model was resolved from workflow_context (not re-resolved)
        context_resolved = [m for m in result2.models_resolved if m.match_type == "workflow_context"]
        assert len(context_resolved) > 0, "Should have at least one model resolved from context"

        # Verify pyproject has the model data (validates full ManifestWorkflowModel was used)
        workflow_models = test_env.pyproject.workflows.get_workflow_models("test")
        assert len(workflow_models) > 0, "Should have workflow models in pyproject"
        assert workflow_models[0].hash is not None, "Model should have hash (resolved)"


class TestSchemaChanges:
    """Test schema changes to support download intents."""

    def test_manifest_workflow_model_has_relative_path(self):
        """Test ManifestWorkflowModel includes relative_path field."""
        from comfygit_core.models.manifest import ManifestWorkflowModel
        from comfygit_core.models.workflow import WorkflowNodeWidgetRef

        # ACT - Create ManifestWorkflowModel with relative_path
        model = ManifestWorkflowModel(
            filename="test.safetensors",
            category="checkpoints",
            criticality="flexible",
            status="unresolved",
            nodes=[WorkflowNodeWidgetRef(
                node_id="1",
                node_type="CheckpointLoaderSimple",
                widget_index=0,
                widget_value="test.safetensors"
            )],
            sources=["https://example.com/model"],
            relative_path="checkpoints/test.safetensors"
        )

        # ASSERT
        assert model.relative_path == "checkpoints/test.safetensors"

        # Test TOML serialization includes relative_path
        toml_dict = model.to_toml_dict()
        assert "relative_path" in toml_dict
        assert toml_dict["relative_path"] == "checkpoints/test.safetensors"

    def test_resolved_model_has_target_path(self):
        """Test ResolvedModel includes target_path field."""
        from comfygit_core.models.workflow import ResolvedModel, WorkflowNodeWidgetRef

        # ACT - Create ResolvedModel with target_path
        ref = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="model.safetensors"
        )

        resolved = ResolvedModel(
            workflow="test",
            reference=ref,
            resolved_model=None,
            model_source="https://example.com/model",
            is_optional=False,
            match_type="download_intent",
            target_path=Path("checkpoints/model.safetensors")
        )

        # ASSERT
        assert resolved.target_path == Path("checkpoints/model.safetensors")

    def test_resolution_result_has_download_intents_property(self):
        """Test ResolutionResult.has_download_intents property."""
        from comfygit_core.models.workflow import ResolutionResult, ResolvedModel, WorkflowNodeWidgetRef

        # ARRANGE - Create result with download intent
        ref = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="CheckpointLoaderSimple",
            widget_index=0,
            widget_value="model.safetensors"
        )

        download_intent = ResolvedModel(
            workflow="test",
            reference=ref,
            resolved_model=None,
            model_source="https://example.com/model",
            is_optional=False,
            match_type="download_intent",
            target_path=Path("checkpoints/model.safetensors")
        )

        # ACT
        result_with_intent = ResolutionResult(
            workflow_name="test",
            models_resolved=[download_intent]
        )

        result_without_intent = ResolutionResult(
            workflow_name="test",
            models_resolved=[]
        )

        # ASSERT
        assert result_with_intent.has_download_intents is True
        assert result_without_intent.has_download_intents is False

    def test_batch_download_callbacks_dataclass(self):
        """Test BatchDownloadCallbacks dataclass exists with correct signature."""
        from comfygit_core.models.workflow import BatchDownloadCallbacks

        # ACT - Create callbacks with all fields
        callbacks = BatchDownloadCallbacks(
            on_batch_start=lambda count: None,
            on_file_start=lambda name, idx, total: None,
            on_file_progress=lambda downloaded, total: None,
            on_file_complete=lambda name, success, error: None,
            on_batch_complete=lambda success, total: None
        )

        # ASSERT - All fields exist
        assert hasattr(callbacks, 'on_batch_start')
        assert hasattr(callbacks, 'on_file_start')
        assert hasattr(callbacks, 'on_file_progress')
        assert hasattr(callbacks, 'on_file_complete')
        assert hasattr(callbacks, 'on_batch_complete')

        # All should be optional (can be None)
        callbacks_empty = BatchDownloadCallbacks()
        assert callbacks_empty.on_batch_start is None
        assert callbacks_empty.on_file_start is None


class TestPropertyDownloadIntentRegression:
    """Regression tests for property_download_intent handling.

    Bug: Workflows with models that have download URLs embedded in node properties
    (match_type="property_download_intent") were incorrectly not counted as having
    download intents, because only "download_intent" was being checked.

    This caused:
    - has_download_intents to return False
    - has_issues to return False
    - download_intents_count to return 0
    - Status showing "No issues" when there were pending downloads
    """

    def test_has_download_intents_includes_property_download_intent(self):
        """ResolutionResult.has_download_intents should return True for property_download_intent."""
        from comfygit_core.models.workflow import ResolutionResult, ResolvedModel, WorkflowNodeWidgetRef

        # ARRANGE - Create result with property_download_intent (from node properties)
        ref = WorkflowNodeWidgetRef(
            node_id="1",
            node_type="VAELoader",
            widget_index=0,
            widget_value="qwen_image_vae.safetensors",
            property_url="https://huggingface.co/example/model.safetensors"
        )

        property_intent = ResolvedModel(
            workflow="test",
            reference=ref,
            resolved_model=None,
            model_source="https://huggingface.co/example/model.safetensors",
            is_optional=False,
            match_type="property_download_intent",  # From node properties, not pyproject
            target_path=Path("vae/qwen_image_vae.safetensors")
        )

        # ACT
        result = ResolutionResult(
            workflow_name="test",
            models_resolved=[property_intent]
        )

        # ASSERT - property_download_intent should be counted as a download intent
        assert result.has_download_intents is True, \
            "has_download_intents should return True for property_download_intent"

    def test_has_download_intents_includes_both_intent_types(self):
        """ResolutionResult.has_download_intents should return True for either intent type."""
        from comfygit_core.models.workflow import ResolutionResult, ResolvedModel, WorkflowNodeWidgetRef

        ref1 = WorkflowNodeWidgetRef(
            node_id="1", node_type="CheckpointLoaderSimple",
            widget_index=0, widget_value="model1.safetensors"
        )
        ref2 = WorkflowNodeWidgetRef(
            node_id="2", node_type="VAELoader",
            widget_index=0, widget_value="model2.safetensors",
            property_url="https://example.com/model2.safetensors"
        )

        # Standard download_intent (from pyproject)
        standard_intent = ResolvedModel(
            workflow="test", reference=ref1, resolved_model=None,
            model_source="https://civitai.com/api/download/123",
            match_type="download_intent", target_path=Path("checkpoints/model1.safetensors")
        )

        # Property download_intent (from node properties)
        property_intent = ResolvedModel(
            workflow="test", reference=ref2, resolved_model=None,
            model_source="https://example.com/model2.safetensors",
            match_type="property_download_intent", target_path=Path("vae/model2.safetensors")
        )

        # Test with only standard intent
        result_standard = ResolutionResult(workflow_name="test", models_resolved=[standard_intent])
        assert result_standard.has_download_intents is True

        # Test with only property intent
        result_property = ResolutionResult(workflow_name="test", models_resolved=[property_intent])
        assert result_property.has_download_intents is True

        # Test with both
        result_both = ResolutionResult(workflow_name="test", models_resolved=[standard_intent, property_intent])
        assert result_both.has_download_intents is True

    def test_workflow_analysis_status_has_issues_for_property_download_intent(self):
        """WorkflowAnalysisStatus.has_issues should return True for property_download_intent."""
        from comfygit_core.models.workflow import (
            WorkflowAnalysisStatus, ResolutionResult, ResolvedModel,
            WorkflowNodeWidgetRef, WorkflowDependencies
        )

        ref = WorkflowNodeWidgetRef(
            node_id="1", node_type="UNETLoader",
            widget_index=0, widget_value="qwen_model.safetensors",
            property_url="https://huggingface.co/qwen/model.safetensors"
        )

        property_intent = ResolvedModel(
            workflow="test", reference=ref, resolved_model=None,
            model_source="https://huggingface.co/qwen/model.safetensors",
            match_type="property_download_intent",
            target_path=Path("unet/qwen_model.safetensors")
        )

        resolution = ResolutionResult(
            workflow_name="test",
            models_resolved=[property_intent]
        )

        dependencies = WorkflowDependencies(
            workflow_name="test",
            found_models=[]
        )

        # ACT
        status = WorkflowAnalysisStatus(
            name="test",
            sync_state="new",
            dependencies=dependencies,
            resolution=resolution,
            uninstalled_nodes=[]
        )

        # ASSERT - has_issues should be True due to property_download_intent
        assert status.has_issues is True, \
            "has_issues should return True for workflows with property_download_intent"

    def test_download_intents_count_includes_property_download_intent(self):
        """WorkflowAnalysisStatus.download_intents_count should count property_download_intent."""
        from comfygit_core.models.workflow import (
            WorkflowAnalysisStatus, ResolutionResult, ResolvedModel,
            WorkflowNodeWidgetRef, WorkflowDependencies
        )

        refs = [
            WorkflowNodeWidgetRef(node_id=str(i), node_type="Loader", widget_index=0, widget_value=f"model{i}.safetensors")
            for i in range(4)
        ]

        # Mix of intent types
        models = [
            ResolvedModel(workflow="test", reference=refs[0], resolved_model=None,
                          model_source="https://a.com", match_type="download_intent",
                          target_path=Path("a.safetensors")),
            ResolvedModel(workflow="test", reference=refs[1], resolved_model=None,
                          model_source="https://b.com", match_type="property_download_intent",
                          target_path=Path("b.safetensors")),
            ResolvedModel(workflow="test", reference=refs[2], resolved_model=None,
                          model_source="https://c.com", match_type="property_download_intent",
                          target_path=Path("c.safetensors")),
            ResolvedModel(workflow="test", reference=refs[3], resolved_model=None,
                          model_source=None, match_type="exact",  # Not a download intent
                          target_path=None),
        ]

        resolution = ResolutionResult(workflow_name="test", models_resolved=models)
        dependencies = WorkflowDependencies(workflow_name="test", found_models=[])

        status = WorkflowAnalysisStatus(
            name="test", sync_state="new",
            dependencies=dependencies, resolution=resolution,
            uninstalled_nodes=[]
        )

        # ASSERT - Should count both download_intent (1) and property_download_intent (2) = 3
        assert status.download_intents_count == 3, \
            f"download_intents_count should be 3, got {status.download_intents_count}"

    def test_issue_summary_includes_property_download_intents(self):
        """WorkflowAnalysisStatus.issue_summary should mention pending downloads for property_download_intent."""
        from comfygit_core.models.workflow import (
            WorkflowAnalysisStatus, ResolutionResult, ResolvedModel,
            WorkflowNodeWidgetRef, WorkflowDependencies
        )

        ref = WorkflowNodeWidgetRef(
            node_id="1", node_type="VAELoader",
            widget_index=0, widget_value="model.safetensors",
            property_url="https://example.com/model.safetensors"
        )

        property_intent = ResolvedModel(
            workflow="test", reference=ref, resolved_model=None,
            model_source="https://example.com/model.safetensors",
            match_type="property_download_intent",
            target_path=Path("vae/model.safetensors")
        )

        resolution = ResolutionResult(workflow_name="test", models_resolved=[property_intent])
        dependencies = WorkflowDependencies(workflow_name="test", found_models=[])

        status = WorkflowAnalysisStatus(
            name="test", sync_state="new",
            dependencies=dependencies, resolution=resolution,
            uninstalled_nodes=[]
        )

        # ASSERT - issue_summary should mention pending downloads
        assert "pending download" in status.issue_summary.lower(), \
            f"issue_summary should mention pending downloads, got: {status.issue_summary}"
