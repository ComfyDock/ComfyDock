"""Integration test for model category mismatch detection.

Tests that status correctly detects when a model exists but is in the wrong
category directory for the node that needs it (e.g., LoRA in checkpoints/).
This is functionally different from path_sync issues - category mismatch means
ComfyUI cannot load the model at runtime.
"""

import sys
from pathlib import Path

# Import helpers
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.workflow_builder import WorkflowBuilder


class TestModelCategoryMismatchDetection:
    """Test detection of models in wrong category directories for their loader nodes."""

    def test_detects_lora_in_checkpoints_directory(self, test_env, test_workspace):
        """Test that status flags LoRA model in checkpoints/ as category mismatch.

        Scenario:
        1. User downloads LoRA model but overrides path to checkpoints/
        2. Model exists, is hashed, is indexed in pyproject.toml
        3. Workflow uses LoraLoader which only scans models/loras/
        4. ComfyUI fails at runtime - can't find model in loras/
        5. Status should detect this as a blocking issue
        """
        # ARRANGE: Create model in checkpoints/ (WRONG for LoRA)
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="style_lora.safetensors",
            relative_path="checkpoints",  # WRONG! Should be in loras/
            category="checkpoints"
        )
        model_builder.index_all()

        # Create workflow with LoraLoader referencing the model
        workflow = (
            WorkflowBuilder()
            .add_lora_loader("style_lora.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # ACT: Get workflow status
        workflow_status = test_env.workflow_manager.get_workflow_status()

        # Find our workflow
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "test_workflow"),
            None
        )
        assert test_wf is not None, "test_workflow should exist in status"

        # ASSERT: Model should be resolved (found by filename)
        assert len(test_wf.resolution.models_resolved) == 1, \
            "Model should resolve by filename match"

        resolved_model = test_wf.resolution.models_resolved[0]

        # FAIL POINT 1: ResolvedModel should have category mismatch fields
        assert hasattr(resolved_model, 'has_category_mismatch'), \
            "ResolvedModel should have has_category_mismatch field"

        assert resolved_model.has_category_mismatch is True, \
            "Should flag that model in checkpoints/ is wrong for LoraLoader"

        assert hasattr(resolved_model, 'expected_categories'), \
            "ResolvedModel should have expected_categories field"

        assert resolved_model.expected_categories == ["loras"], \
            f"Expected categories should be ['loras'], got {resolved_model.expected_categories}"

        assert hasattr(resolved_model, 'actual_category'), \
            "ResolvedModel should have actual_category field"

        assert resolved_model.actual_category == "checkpoints", \
            f"Actual category should be 'checkpoints', got {resolved_model.actual_category}"

        # FAIL POINT 2: WorkflowAnalysisStatus should track category mismatch
        assert hasattr(test_wf, 'models_with_category_mismatch_count'), \
            "WorkflowAnalysisStatus should track category mismatch count"

        assert test_wf.models_with_category_mismatch_count == 1, \
            "Should count 1 model with category mismatch"

        assert hasattr(test_wf, 'has_category_mismatch_issues'), \
            "WorkflowAnalysisStatus should have has_category_mismatch_issues property"

        assert test_wf.has_category_mismatch_issues is True, \
            "Should indicate workflow has category mismatch issues"

        # FAIL POINT 3: has_issues should include category mismatch
        assert test_wf.has_issues is True, \
            "Category mismatch should make has_issues=True (blocking issue)"

        # FAIL POINT 4: issue_summary should mention category mismatch
        assert "wrong directory" in test_wf.issue_summary.lower(), \
            f"issue_summary should mention wrong directory, got: {test_wf.issue_summary}"

    def test_model_in_correct_category_not_flagged(self, test_env, test_workspace):
        """Test that model in correct category is NOT flagged as mismatch."""
        # ARRANGE: Create LoRA model in correct directory
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="correct_lora.safetensors",
            relative_path="loras",  # CORRECT for LoRA
            category="loras"
        )
        model_builder.index_all()

        # Create workflow with LoraLoader
        workflow = (
            WorkflowBuilder()
            .add_lora_loader("correct_lora.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "correct_workflow", workflow)

        # ACT
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "correct_workflow"),
            None
        )

        # ASSERT: Should not be flagged
        assert test_wf is not None
        assert len(test_wf.resolution.models_resolved) == 1

        resolved_model = test_wf.resolution.models_resolved[0]
        assert resolved_model.has_category_mismatch is False, \
            "Model in correct category should not be flagged"

        assert test_wf.has_category_mismatch_issues is False
        assert test_wf.models_with_category_mismatch_count == 0

    def test_custom_nodes_skipped_for_category_validation(self, test_env, test_workspace):
        """Test that custom nodes don't trigger category mismatch warnings.

        Custom nodes manage their own model paths - we don't know what directories
        they scan, so we skip category validation entirely.
        """
        # ARRANGE: Create model in "wrong" location
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="custom_model.safetensors",
            relative_path="checkpoints",
            category="checkpoints"
        )
        model_builder.index_all()

        # Create workflow with custom node
        workflow = (
            WorkflowBuilder()
            .add_custom_node("CustomModelLoader", ["custom_model.safetensors"])
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "custom_workflow", workflow)

        # ACT
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "custom_workflow"),
            None
        )

        # ASSERT: Custom nodes should not be validated for category
        assert test_wf is not None
        assert test_wf.has_category_mismatch_issues is False, \
            "Custom nodes should skip category validation"

    def test_unresolved_models_not_checked_for_category(self, test_env, test_workspace):
        """Test that unresolved models don't trigger category mismatch.

        If a model doesn't exist at all, category mismatch detection is irrelevant.
        """
        # ARRANGE: Create workflow with non-existent model
        workflow = (
            WorkflowBuilder()
            .add_lora_loader("nonexistent.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "missing_workflow", workflow)

        # ACT
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "missing_workflow"),
            None
        )

        # ASSERT: Model should be unresolved, no category mismatch
        assert test_wf is not None
        assert len(test_wf.resolution.models_unresolved) == 1, \
            "Model should be unresolved"
        assert test_wf.models_with_category_mismatch_count == 0, \
            "Unresolved models should not count as category mismatch"

    def test_checkpoint_in_loras_flagged(self, test_env, test_workspace):
        """Test that checkpoint model in loras/ is flagged as category mismatch."""
        # ARRANGE: Create checkpoint in loras/ (WRONG)
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="sdxl_model.safetensors",
            relative_path="loras",  # WRONG! Should be in checkpoints/
            category="loras"
        )
        model_builder.index_all()

        # Create workflow with CheckpointLoaderSimple
        workflow = (
            WorkflowBuilder()
            .add_checkpoint_loader("sdxl_model.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "checkpoint_workflow", workflow)

        # ACT
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "checkpoint_workflow"),
            None
        )

        # ASSERT
        assert test_wf is not None
        assert len(test_wf.resolution.models_resolved) == 1

        resolved_model = test_wf.resolution.models_resolved[0]
        assert resolved_model.has_category_mismatch is True, \
            "Model in loras/ should be flagged for CheckpointLoaderSimple"

        assert "checkpoints" in resolved_model.expected_categories, \
            f"Expected checkpoints in {resolved_model.expected_categories}"

        assert resolved_model.actual_category == "loras", \
            f"Actual should be loras, got {resolved_model.actual_category}"

    def test_model_in_multiple_locations_prefers_correct_category(self, test_env, test_workspace):
        """Test that when model exists in multiple locations, correct category is preferred.

        Scenario:
        1. User downloads LoRA to checkpoints/ by mistake
        2. Model is resolved and saved to pyproject.toml with its hash
        3. User copies (not moves) file to loras/
        4. Model now exists in BOTH locations with same hash
        5. On subsequent status check (from pyproject context), should NOT flag mismatch
           because the model exists in a valid location (loras/)

        This is a regression test for the bug where:
        - _try_context_resolution looks up model by hash
        - get_model() returns first location alphabetically (checkpoints/ < loras/)
        - _check_category_mismatch only checks that one location
        - Even though loras/ exists, mismatch is falsely flagged
        """
        # ARRANGE Step 1: Create model in checkpoints/ (WRONG location)
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="dual_location_lora.safetensors",
            relative_path="checkpoints",  # Wrong location
            category="checkpoints"
        )
        model_builder.index_all()

        # Create workflow with LoraLoader
        workflow = (
            WorkflowBuilder()
            .add_lora_loader("dual_location_lora.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "dual_location_workflow", workflow)

        # ARRANGE Step 2: First resolution - model gets saved to pyproject.toml
        # This simulates `cg workflow resolve` which saves the model with its hash
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "dual_location_workflow"),
            None
        )
        assert test_wf is not None

        # At this point, model should be flagged (only in checkpoints/)
        resolved_model = test_wf.resolution.models_resolved[0]
        assert resolved_model.has_category_mismatch is True, \
            "Before copy: model only in checkpoints/ should flag mismatch"

        # Apply resolution to save to pyproject.toml (this writes the hash)
        test_env.workflow_manager.apply_resolution(test_wf.resolution)

        # ARRANGE Step 3: User copies model to correct location (loras/)
        wrong_path = test_workspace.workspace_config_manager.get_models_directory() / "checkpoints/dual_location_lora.safetensors"
        content = wrong_path.read_bytes()

        correct_path = test_workspace.workspace_config_manager.get_models_directory() / "loras/dual_location_lora.safetensors"
        correct_path.parent.mkdir(parents=True, exist_ok=True)
        correct_path.write_bytes(content)

        # Re-scan to pick up the new location
        test_workspace.sync_model_directory()

        # ACT: Get workflow status AGAIN (this time model is in pyproject.toml)
        # Resolution will use Strategy 0 (_try_context_resolution) which looks up by hash
        workflow_status_2 = test_env.workflow_manager.get_workflow_status()
        test_wf_2 = next(
            (wf for wf in workflow_status_2.analyzed_workflows if wf.name == "dual_location_workflow"),
            None
        )

        # ASSERT: Model should be resolved
        assert test_wf_2 is not None, "Workflow should exist"
        assert len(test_wf_2.resolution.models_resolved) == 1, \
            "Model should resolve"

        resolved_model_2 = test_wf_2.resolution.models_resolved[0]

        # KEY ASSERTION: Since model now exists in loras/, no mismatch should be flagged
        # The system should check ALL locations, not just the first alphabetically
        assert resolved_model_2.has_category_mismatch is False, \
            f"Model exists in loras/, should NOT flag category mismatch. " \
            f"Got actual_category={resolved_model_2.actual_category}, " \
            f"expected_categories={resolved_model_2.expected_categories}"

        assert test_wf_2.has_category_mismatch_issues is False, \
            "Workflow should NOT have category mismatch issues when correct location exists"

    def test_clip_loader_accepts_text_encoders_with_dynamic_config(self, test_env, test_workspace):
        """Test CLIPLoader accepts model in text_encoders/ when dynamic config maps both.

        With dynamic config, CLIPLoader should accept models in BOTH text_encoders/ and clip/
        since folder_mappings indicates they're equivalent directories.
        """
        # ARRANGE: Create dynamic config mapping text_encoders and clip together
        import json
        cec_path = test_env.path / ".cec"
        folder_paths_data = {
            "metadata": {
                "extraction_date": "2026-01-21T12:00:00",
                "comfyui_version": "v0.3.68",
            },
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
            },
            "legacy_aliases": {
                "clip": "text_encoders",
            },
        }
        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        # Create model in text_encoders/ directory
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="clip_model.safetensors",
            relative_path="text_encoders",
            category="text_encoders"
        )
        model_builder.index_all()

        # Create workflow with CLIPLoader
        workflow = (
            WorkflowBuilder()
            .add_clip_loader("clip_model.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "clip_workflow", workflow)

        # ACT: Get workflow status (ModelResolver should reload config with cec_path)
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "clip_workflow"),
            None
        )

        # ASSERT: Model in text_encoders/ should NOT be flagged as mismatch
        assert test_wf is not None
        assert len(test_wf.resolution.models_resolved) == 1

        resolved_model = test_wf.resolution.models_resolved[0]
        assert resolved_model.has_category_mismatch is False, \
            f"CLIPLoader should accept text_encoders/ with dynamic config. " \
            f"Got actual_category={resolved_model.actual_category}, " \
            f"expected_categories={resolved_model.expected_categories}"

        # Verify expected_categories contains both directories
        assert "text_encoders" in resolved_model.expected_categories, \
            "Expected categories should include text_encoders"
        assert "clip" in resolved_model.expected_categories, \
            "Expected categories should include clip (from dynamic config)"

        assert test_wf.has_category_mismatch_issues is False

    def test_clip_loader_accepts_clip_with_dynamic_config(self, test_env, test_workspace):
        """Test CLIPLoader accepts model in clip/ when dynamic config maps both.

        Verifies the reverse case: clip/ directory is also valid for CLIPLoader.
        """
        # ARRANGE: Create dynamic config
        import json
        cec_path = test_env.path / ".cec"
        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
            },
            "legacy_aliases": {},
        }
        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        # Create model in clip/ directory
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="clip_v2.safetensors",
            relative_path="clip",
            category="clip"
        )
        model_builder.index_all()

        # Create workflow with CLIPLoader
        workflow = (
            WorkflowBuilder()
            .add_clip_loader("clip_v2.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "clip_v2_workflow", workflow)

        # ACT
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "clip_v2_workflow"),
            None
        )

        # ASSERT: Model in clip/ should NOT be flagged as mismatch
        assert test_wf is not None
        assert len(test_wf.resolution.models_resolved) == 1

        resolved_model = test_wf.resolution.models_resolved[0]
        assert resolved_model.has_category_mismatch is False, \
            f"CLIPLoader should accept clip/ with dynamic config. " \
            f"Got actual_category={resolved_model.actual_category}, " \
            f"expected_categories={resolved_model.expected_categories}"

        assert test_wf.has_category_mismatch_issues is False

    def test_clip_loader_still_flags_wrong_directory_with_dynamic_config(self, test_env, test_workspace):
        """Test CLIPLoader still flags model in loras/ as mismatch even with dynamic config.

        Ensures that dynamic config doesn't break normal mismatch detection.
        """
        # ARRANGE: Create dynamic config
        import json
        cec_path = test_env.path / ".cec"
        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "text_encoders": ["text_encoders", "clip"],
            },
            "legacy_aliases": {},
        }
        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        # Create model in loras/ (WRONG for CLIPLoader)
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="misplaced_clip.safetensors",
            relative_path="loras",
            category="loras"
        )
        model_builder.index_all()

        # Create workflow with CLIPLoader
        workflow = (
            WorkflowBuilder()
            .add_clip_loader("misplaced_clip.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "misplaced_clip_workflow", workflow)

        # ACT
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "misplaced_clip_workflow"),
            None
        )

        # ASSERT: Model in loras/ SHOULD be flagged as mismatch
        assert test_wf is not None
        assert len(test_wf.resolution.models_resolved) == 1

        resolved_model = test_wf.resolution.models_resolved[0]
        assert resolved_model.has_category_mismatch is True, \
            "CLIPLoader should flag model in loras/ as mismatch"

        assert resolved_model.actual_category == "loras"
        assert "loras" not in resolved_model.expected_categories, \
            "loras should not be in expected categories for CLIPLoader"

        assert test_wf.has_category_mismatch_issues is True

    def test_unet_loader_accepts_unet_with_dynamic_config(self, test_env, test_workspace):
        """Test UNETLoader accepts model in unet/ when dynamic config maps it.

        UNETLoader traditionally uses diffusion_models/, but with dynamic config
        should also accept unet/ directory.
        """
        # ARRANGE: Create dynamic config
        import json
        cec_path = test_env.path / ".cec"
        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "diffusion_models": ["unet", "diffusion_models"],
            },
            "legacy_aliases": {
                "unet": "diffusion_models",
            },
        }
        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        # Create model in unet/ directory
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="flux_unet.safetensors",
            relative_path="unet",
            category="unet"
        )
        model_builder.index_all()

        # Create workflow with UNETLoader
        workflow = (
            WorkflowBuilder()
            .add_unet_loader("flux_unet.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "unet_workflow", workflow)

        # ACT
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "unet_workflow"),
            None
        )

        # ASSERT: Model in unet/ should NOT be flagged as mismatch
        assert test_wf is not None
        assert len(test_wf.resolution.models_resolved) == 1

        resolved_model = test_wf.resolution.models_resolved[0]
        assert resolved_model.has_category_mismatch is False, \
            f"UNETLoader should accept unet/ with dynamic config. " \
            f"Got actual_category={resolved_model.actual_category}, " \
            f"expected_categories={resolved_model.expected_categories}"

        # Verify both directories are in expected_categories
        assert "unet" in resolved_model.expected_categories
        assert "diffusion_models" in resolved_model.expected_categories

        assert test_wf.has_category_mismatch_issues is False

    def test_unet_loader_accepts_diffusion_models_with_dynamic_config(self, test_env, test_workspace):
        """Test UNETLoader accepts model in diffusion_models/ with dynamic config.

        Verifies traditional directory still works with dynamic config.
        """
        # ARRANGE: Create dynamic config
        import json
        cec_path = test_env.path / ".cec"
        folder_paths_data = {
            "metadata": {},
            "folder_mappings": {
                "diffusion_models": ["unet", "diffusion_models"],
            },
            "legacy_aliases": {},
        }
        folder_paths_file = cec_path / "comfyui_folder_paths.json"
        with open(folder_paths_file, "w") as f:
            json.dump(folder_paths_data, f)

        # Create model in diffusion_models/ directory
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="sd3_unet.safetensors",
            relative_path="diffusion_models",
            category="diffusion_models"
        )
        model_builder.index_all()

        # Create workflow with UNETLoader
        workflow = (
            WorkflowBuilder()
            .add_unet_loader("sd3_unet.safetensors")
            .build()
        )
        simulate_comfyui_save_workflow(test_env, "diffusion_workflow", workflow)

        # ACT
        workflow_status = test_env.workflow_manager.get_workflow_status()
        test_wf = next(
            (wf for wf in workflow_status.analyzed_workflows if wf.name == "diffusion_workflow"),
            None
        )

        # ASSERT: Model in diffusion_models/ should NOT be flagged as mismatch
        assert test_wf is not None
        assert len(test_wf.resolution.models_resolved) == 1

        resolved_model = test_wf.resolution.models_resolved[0]
        assert resolved_model.has_category_mismatch is False, \
            "UNETLoader should accept diffusion_models/ with dynamic config"

        assert test_wf.has_category_mismatch_issues is False
