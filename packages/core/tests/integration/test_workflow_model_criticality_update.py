"""Integration tests for updating model criticality after resolution.

Tests the ability to change model criticality (required/flexible/optional)
after initial workflow resolution without re-resolving the entire workflow.
"""

import sys
from pathlib import Path

import pytest

# Import helpers
sys.path.insert(0, str(Path(__file__).parent.parent))
from comfygit_core.strategies.auto import AutoModelStrategy, AutoNodeStrategy
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.pyproject_assertions import PyprojectAssertions
from helpers.workflow_builder import make_minimal_workflow


class TestModelCriticalityUpdate:
    """Test updating model criticality for resolved workflows."""

    def test_update_criticality_by_filename(self, test_env, test_workspace):
        """Test updating model criticality using filename as identifier.

        Scenario: Developer resolves a workflow with a checkpoint (default: flexible),
        then realizes the workflow works fine without it (should be: optional).
        """
        # ARRANGE: Create model and resolve workflow
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="sd15_model.safetensors",
            relative_path="checkpoints",
            category="checkpoints"
        )
        model_builder.index_all()

        workflow = make_minimal_workflow("sd15_model.safetensors")
        simulate_comfyui_save_workflow(test_env, "utilities", workflow)

        # Initial resolution
        test_env.resolve_workflow(
            name="utilities",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # Verify initial state: checkpoint gets "flexible" by default
        assertions = PyprojectAssertions(test_env)
        (
            assertions
            .has_workflow("utilities")
            .has_model_with_filename("sd15_model.safetensors")
            .has_criticality("flexible")
        )

        # ACT: Update criticality to optional
        success = test_env.workflow_manager.update_model_criticality(
            workflow_name="utilities",
            model_identifier="sd15_model.safetensors",
            new_criticality="optional"
        )

        # ASSERT: Update succeeded
        assert success, "update_model_criticality should return True on success"

        # Verify criticality was updated (need fresh assertions to reload pyproject)
        fresh_assertions = PyprojectAssertions(test_env)
        (
            fresh_assertions
            .has_workflow("utilities")
            .has_model_with_filename("sd15_model.safetensors")
            .has_criticality("optional")
        )

    def test_update_criticality_by_hash(self, test_env, test_workspace):
        """Test updating model criticality using hash as identifier."""
        # ARRANGE: Create checkpoint model and resolve
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model(
            filename="model.safetensors",
            relative_path="checkpoints",
            category="checkpoints"
        )
        model_builder.index_all()

        workflow = make_minimal_workflow("model.safetensors")
        simulate_comfyui_save_workflow(test_env, "test_hash", workflow)

        result = test_env.resolve_workflow(
            name="test_hash",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # Get the ACTUAL hash from the resolved model (not from builder)
        assert len(result.models_resolved) == 1, "Should have resolved one model"
        actual_hash = result.models_resolved[0].resolved_model.hash

        # ACT: Update using hash instead of filename
        success = test_env.workflow_manager.update_model_criticality(
            workflow_name="test_hash",
            model_identifier=actual_hash,  # Using actual hash from resolution
            new_criticality="optional"
        )

        # ASSERT
        assert success, f"Should find model by hash {actual_hash}"

        fresh_assertions = PyprojectAssertions(test_env)
        (
            fresh_assertions
            .has_workflow("test_hash")
            .has_model_with_filename("model.safetensors")  # Find by filename
            .has_criticality("optional")
        )

        # Also verify it has the expected hash
        fresh_assertions.has_workflow("test_hash").has_model_with_hash(actual_hash)

    def test_update_criticality_model_not_found(self, test_env, test_workspace):
        """Test update fails gracefully when model doesn't exist."""
        # ARRANGE: Workflow without models
        workflow = make_minimal_workflow("sd15.safetensors")
        simulate_comfyui_save_workflow(test_env, "empty", workflow)

        # ACT: Try to update non-existent model
        success = test_env.workflow_manager.update_model_criticality(
            workflow_name="empty",
            model_identifier="nonexistent.safetensors",
            new_criticality="optional"
        )

        # ASSERT: Should return False
        assert not success, "Should return False when model not found"

    def test_update_criticality_invalid_value(self, test_env, test_workspace):
        """Test that invalid criticality values are rejected."""
        # ARRANGE: Resolve workflow
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model("model.safetensors", "checkpoints")
        model_builder.index_all()

        workflow = make_minimal_workflow("model.safetensors")
        simulate_comfyui_save_workflow(test_env, "test_invalid", workflow)
        test_env.resolve_workflow(
            name="test_invalid",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # ACT & ASSERT: Invalid criticality should raise ValueError
        with pytest.raises(ValueError, match="Invalid criticality"):
            test_env.workflow_manager.update_model_criticality(
                workflow_name="test_invalid",
                model_identifier="model.safetensors",
                new_criticality="super_critical"  # Invalid!
            )

    def test_update_all_criticality_levels(self, test_env, test_workspace):
        """Test updating between all criticality levels (required/flexible/optional)."""
        # ARRANGE: Create multiple models with different defaults
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model("checkpoint.safetensors", "checkpoints")  # Default: flexible
        model_builder.add_model("lora.safetensors", "loras")  # Default: required
        model_builder.add_model("upscale.pth", "upscale_models")  # Default: optional
        model_builder.index_all()

        workflow = make_minimal_workflow("checkpoint.safetensors")
        # Add other nodes
        workflow["nodes"].append({
            "id": "2",
            "type": "LoraLoader",
            "widgets_values": ["lora.safetensors", 1.0, 1.0]
        })
        workflow["nodes"].append({
            "id": "3",
            "type": "UpscaleModelLoader",
            "widgets_values": ["upscale.pth"]
        })
        simulate_comfyui_save_workflow(test_env, "test_levels", workflow)

        test_env.resolve_workflow(
            name="test_levels",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        assertions = PyprojectAssertions(test_env)

        # Verify initial defaults
        (
            assertions
            .has_workflow("test_levels")
            .has_model_with_filename("checkpoint.safetensors")
            .has_criticality("flexible")
            .and_workflow()
            .has_model_with_filename("lora.safetensors")
            .has_criticality("flexible")
            .and_workflow()
            .has_model_with_filename("upscale.pth")
            .has_criticality("flexible")
        )

        # ACT: Update each to different levels
        test_env.workflow_manager.update_model_criticality(
            "test_levels", "checkpoint.safetensors", "required"
        )
        test_env.workflow_manager.update_model_criticality(
            "test_levels", "lora.safetensors", "optional"
        )
        test_env.workflow_manager.update_model_criticality(
            "test_levels", "upscale.pth", "flexible"
        )

        # ASSERT: All updates applied (fresh assertions to reload pyproject)
        fresh_assertions = PyprojectAssertions(test_env)
        (
            fresh_assertions
            .has_workflow("test_levels")
            .has_model_with_filename("checkpoint.safetensors")
            .has_criticality("required")
            .and_workflow()
            .has_model_with_filename("lora.safetensors")
            .has_criticality("optional")
            .and_workflow()
            .has_model_with_filename("upscale.pth")
            .has_criticality("flexible")
        )

    def test_update_unresolved_model_criticality(self, test_env, test_workspace):
        """Test updating criticality for unresolved models (no hash)."""
        # ARRANGE: Workflow with missing model
        workflow = make_minimal_workflow("missing_model.safetensors")
        simulate_comfyui_save_workflow(test_env, "test_unresolved", workflow)

        # Resolve (will be unresolved)
        test_env.resolve_workflow(
            name="test_unresolved",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # Verify it's unresolved with default criticality
        assertions = PyprojectAssertions(test_env)
        (
            assertions
            .has_workflow("test_unresolved")
            .has_model_with_filename("missing_model.safetensors")
            .has_status("unresolved")
            .has_criticality("flexible")  # Default for checkpoints
        )

        # ACT: Update unresolved model to optional
        success = test_env.workflow_manager.update_model_criticality(
            workflow_name="test_unresolved",
            model_identifier="missing_model.safetensors",
            new_criticality="optional"
        )

        # ASSERT: Should work even for unresolved models
        assert success

        fresh_assertions = PyprojectAssertions(test_env)
        (
            fresh_assertions
            .has_workflow("test_unresolved")
            .has_model_with_filename("missing_model.safetensors")
            .has_status("unresolved")  # Still unresolved
            .has_criticality("optional")  # But now optional
        )
