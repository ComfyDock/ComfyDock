"""Integration tests for download intent cache invalidation bug.

Tests that workflow resolution cache properly invalidates when download intents
are added to pyproject.toml, ensuring subsequent status/resolve commands detect
the queued downloads instead of re-prompting the user.

Bug reproduction:
1. User runs `cfd status` → cache stores resolution with model in models_unresolved
2. User runs `cfd workflow resolve` → queues download (sources+path added to pyproject)
3. User runs `cfd status` again → cache NOT invalidated → still shows "models not found"
4. User runs `cfd workflow resolve` again → re-prompts for same model!

Expected behavior:
- Step 3 should show "N models not found, 1 queued for download"
- Step 4 should skip the download intent model and NOT re-prompt
"""

from pathlib import Path
from unittest.mock import Mock

from comfygit_core.models.workflow import ResolvedModel
from conftest import simulate_comfyui_save_workflow
from helpers.workflow_builder import WorkflowBuilder


class TestDownloadIntentCacheInvalidation:
    """Test that cache invalidates when download intents are added."""

    def test_cache_invalidates_when_download_intent_added(self, test_env):
        """Cache should invalidate when download intent (sources+path) is added to pyproject.

        This is a critical bug where the cache doesn't detect download intents,
        causing the CLI to re-prompt users for models they've already queued.
        """
        # ARRANGE - Create workflow with missing model
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("missing_model.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # ACT 1 - First status check (simulates: cfd status)
        # This caches the resolution with model in models_unresolved
        _, resolution1 = test_env.workflow_manager.analyze_and_resolve_workflow("test")

        # ASSERT 1 - Model is unresolved (not in index)
        assert len(resolution1.models_unresolved) == 1
        assert len(resolution1.models_resolved) == 0
        assert resolution1.models_unresolved[0].widget_value == "missing_model.safetensors"

        # ACT 2 - User queues download (simulates: cfd workflow resolve → user enters URL)
        # This writes download intent to pyproject
        download_url = "https://example.com/model.safetensors"
        target_path = Path("checkpoints/missing_model.safetensors")

        mock_strategy = Mock()
        mock_strategy.resolve_model = Mock(
            return_value=ResolvedModel(
                workflow="test",
                reference=resolution1.models_unresolved[0],
                resolved_model=None,
                model_source=download_url,
                is_optional=False,
                match_type="download_intent",
                target_path=target_path
            )
        )

        # Run fix_resolution, which writes download intent through manifest reconciliation.
        test_env.workflow_manager.fix_resolution(
            resolution1,
            model_strategy=mock_strategy
        )

        # ASSERT 2 - Download intent written to pyproject
        workflow_models = test_env.pyproject.workflows.get_workflow_models("test")
        assert len(workflow_models) == 1
        model = workflow_models[0]
        assert model.filename == "missing_model.safetensors"
        assert model.status == "unresolved"
        assert model.sources == [download_url], "Download URL should be saved"
        assert model.relative_path == target_path.as_posix(), "Target path should be saved"

        # ACT 3 - Second status check (simulates: cfd status after queuing download)
        # BUG: Cache should invalidate but doesn't!
        _, resolution2 = test_env.workflow_manager.analyze_and_resolve_workflow("test")

        # ASSERT 3 - THE BUG!
        # Expected: Download intent detected via _try_context_resolution()
        #   → model in models_resolved with match_type="download_intent"
        # Actual: Cache not invalidated, returns stale resolution
        #   → model still in models_unresolved

        download_intents = [m for m in resolution2.models_resolved if m.match_type == "download_intent"]

        # This assertion FAILS due to the bug - download intent not detected
        assert len(download_intents) == 1, (
            f"BUG: Download intent not detected! "
            f"Expected model in models_resolved with match_type='download_intent', "
            f"but got {len(download_intents)} download intents. "
            f"models_unresolved={len(resolution2.models_unresolved)}, "
            f"models_resolved={len(resolution2.models_resolved)}"
        )

        # Verify the download intent has correct data
        intent = download_intents[0]
        assert intent.model_source == download_url
        assert intent.target_path == target_path
        assert intent.reference.widget_value == "missing_model.safetensors"

        # Model should NOT be in unresolved anymore
        assert len(resolution2.models_unresolved) == 0, (
            "Model with download intent should not be in models_unresolved"
        )

    def test_multiple_resolution_sessions_preserve_download_intents(self, test_env):
        """Multiple resolution runs should accumulate download intents without losing previous ones.

        Scenario:
        1. Queue download for model A
        2. Run resolve again for model B
        3. Both download intents should be detected (not re-prompt for A)
        """
        # ARRANGE - Workflow with 2 missing models
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("model_a.safetensors")
            .add_lora_loader("model_b.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # SESSION 1 - Queue download for model A
        download_url_a = "https://example.com/model_a.safetensors"
        target_path_a = Path("checkpoints/model_a.safetensors")

        _, resolution1 = test_env.workflow_manager.analyze_and_resolve_workflow("test")

        # Find model A ref
        model_a_ref = next(
            (ref for ref in resolution1.models_unresolved if ref.widget_value == "model_a.safetensors"),
            None
        )
        assert model_a_ref is not None

        mock_strategy_1 = Mock()
        mock_strategy_1.resolve_model = Mock(
            side_effect=[
                # Model A: Return download intent
                ResolvedModel(
                    workflow="test",
                    reference=model_a_ref,
                    resolved_model=None,
                    model_source=download_url_a,
                    is_optional=False,
                    match_type="download_intent",
                    target_path=target_path_a
                ),
                # Model B: Skip
                None
            ]
        )

        test_env.workflow_manager.fix_resolution(resolution1, model_strategy=mock_strategy_1)

        # ASSERT 1 - Model A has download intent
        workflow_models = test_env.pyproject.workflows.get_workflow_models("test")
        model_a = next((m for m in workflow_models if m.filename == "model_a.safetensors"), None)
        assert model_a is not None
        assert model_a.sources == [download_url_a]

        # SESSION 2 - Queue download for model B
        download_url_b = "https://example.com/model_b.safetensors"
        target_path_b = Path("loras/model_b.safetensors")

        _, resolution2 = test_env.workflow_manager.analyze_and_resolve_workflow("test")

        # BUG: Model A should be detected as download_intent via cache invalidation
        # but it's not, so it appears in models_unresolved again
        download_intents_before_fix = [
            m for m in resolution2.models_resolved if m.match_type == "download_intent"
        ]

        # This FAILS due to cache bug - model A not detected as download intent
        assert len(download_intents_before_fix) == 1, (
            f"BUG: Model A download intent not detected in session 2! "
            f"Expected 1 download intent, got {len(download_intents_before_fix)}"
        )

        # Find model B ref (should be the only unresolved since A has download intent)
        model_b_refs = [
            ref for ref in resolution2.models_unresolved
            if ref.widget_value == "model_b.safetensors"
        ]

        assert len(model_b_refs) == 1, (
            f"Expected only model B in unresolved, but got {len(resolution2.models_unresolved)} unresolved models"
        )

        mock_strategy_2 = Mock()
        mock_strategy_2.resolve_model = Mock(
            return_value=ResolvedModel(
                workflow="test",
                reference=model_b_refs[0],
                resolved_model=None,
                model_source=download_url_b,
                is_optional=False,
                match_type="download_intent",
                target_path=target_path_b
            )
        )

        test_env.workflow_manager.fix_resolution(resolution2, model_strategy=mock_strategy_2)

        # ASSERT 2 - Both download intents preserved
        workflow_models = test_env.pyproject.workflows.get_workflow_models("test")
        assert len(workflow_models) == 2

        model_a = next((m for m in workflow_models if m.filename == "model_a.safetensors"), None)
        assert model_a is not None
        assert model_a.sources == [download_url_a]

        model_b = next((m for m in workflow_models if m.filename == "model_b.safetensors"), None)
        assert model_b is not None
        assert model_b.sources == [download_url_b]

        # SESSION 3 - Status check should detect BOTH download intents
        _, resolution3 = test_env.workflow_manager.analyze_and_resolve_workflow("test")

        download_intents_final = [
            m for m in resolution3.models_resolved if m.match_type == "download_intent"
        ]

        assert len(download_intents_final) == 2, (
            f"BUG: Should detect 2 download intents but got {len(download_intents_final)}"
        )
        assert len(resolution3.models_unresolved) == 0, (
            "No models should be unresolved - both have download intents"
        )

    def test_status_displays_download_intents_correctly(self, test_env):
        """Status command should show 'N queued for download' not 'N not found'.

        This tests the user-facing symptom of the bug where status shows
        "4 models not found" instead of "3 not found, 1 queued for download".
        """
        # ARRANGE - Workflow with 4 missing models
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("model_1.safetensors")
            .add_lora_loader("model_2.safetensors")
            .add_lora_loader("model_3.safetensors")
            .add_lora_loader("model_4.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test", workflow)

        # Queue download for model 1 only
        _, resolution = test_env.workflow_manager.analyze_and_resolve_workflow("test")

        model_1_ref = next(
            (ref for ref in resolution.models_unresolved if ref.widget_value == "model_1.safetensors"),
            None
        )

        mock_strategy = Mock()
        mock_strategy.resolve_model = Mock(
            side_effect=[
                ResolvedModel(
                    workflow="test",
                    reference=model_1_ref,
                    resolved_model=None,
                    model_source="https://example.com/model_1.safetensors",
                    match_type="download_intent",
                    target_path=Path("checkpoints/model_1.safetensors")
                ),
                None,  # Skip model 2
                None,  # Skip model 3
                None,  # Skip model 4
            ]
        )

        test_env.workflow_manager.fix_resolution(resolution, model_strategy=mock_strategy)

        # ACT - Get status (this calls analyze_and_resolve_workflow internally)
        status = test_env.workflow_manager.get_workflow_status()

        # Find our test workflow
        test_workflow = next(
            (w for w in status.analyzed_workflows if w.name == "test"),
            None
        )
        assert test_workflow is not None

        # ASSERT - BUG SYMPTOM
        # Expected: 3 unresolved, 1 download intent
        # Actual: 4 unresolved, 0 download intents (due to cache not invalidating)

        download_intents = [
            m for m in test_workflow.resolution.models_resolved
            if m.match_type == "download_intent"
        ]

        assert len(download_intents) == 1, (
            f"BUG: Status should show 1 queued download but shows {len(download_intents)}"
        )
        assert len(test_workflow.resolution.models_unresolved) == 3, (
            f"BUG: Status should show 3 unresolved but shows {len(test_workflow.resolution.models_unresolved)}"
        )

        # Verify download_intents_count property
        assert test_workflow.download_intents_count == 1

        # Verify issue summary doesn't include download intent model
        assert test_workflow.has_issues  # Still has issues (3 unresolved)
        unresolved_filenames = {ref.widget_value for ref in test_workflow.resolution.models_unresolved}
        assert "model_1.safetensors" not in unresolved_filenames, (
            "Model with download intent should not be in unresolved list"
        )
