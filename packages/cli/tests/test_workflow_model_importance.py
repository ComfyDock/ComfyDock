"""Integration test for workflow model importance command."""

import argparse
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core" / "tests"))
from comfygit_cli.env_commands import EnvironmentCommands
from comfygit_core.workflow import AutoModelStrategy, AutoNodeStrategy
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.pyproject_assertions import PyprojectAssertions
from helpers.workflow_builder import make_minimal_workflow


class TestWorkflowModelImportanceCommand:
    """Test the workflow model importance CLI command."""

    def test_direct_mode_update_single_model(self, test_env, test_workspace):
        """Test direct mode: cg workflow model importance <workflow> <model> <level>."""
        # ARRANGE: Create and resolve workflow with a model
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model("test_model.safetensors", "checkpoints")
        model_builder.index_all()

        workflow = make_minimal_workflow("test_model.safetensors")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        test_env.resolve_workflow(
            name="test_workflow",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # Verify initial state (default: flexible for checkpoints)
        assertions = PyprojectAssertions(test_env)
        (
            assertions
            .has_workflow("test_workflow")
            .has_model_with_filename("test_model.safetensors")
            .has_criticality("flexible")
        )

        # ACT: Update using the workflow manager directly (simulates CLI)
        success = test_env.workflow_manager.update_model_criticality(
            workflow_name="test_workflow",
            model_identifier="test_model.safetensors",
            new_criticality="optional"
        )

        # ASSERT
        assert success, "Should successfully update model criticality"

        fresh_assertions = PyprojectAssertions(test_env)
        (
            fresh_assertions
            .has_workflow("test_workflow")
            .has_model_with_filename("test_model.safetensors")
            .has_criticality("optional")
        )

    def test_update_by_hash(self, test_env, test_workspace):
        """Test updating model importance using hash instead of filename."""
        # ARRANGE
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model("model.safetensors", "checkpoints")
        model_builder.index_all()

        workflow = make_minimal_workflow("model.safetensors")
        simulate_comfyui_save_workflow(test_env, "test_hash", workflow)

        result = test_env.resolve_workflow(
            name="test_hash",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # Get the actual hash from resolved model
        actual_hash = result.models_resolved[0].resolved_model.hash

        # ACT: Update using hash
        success = test_env.workflow_manager.update_model_criticality(
            workflow_name="test_hash",
            model_identifier=actual_hash,
            new_criticality="required"
        )

        # ASSERT
        assert success

        fresh_assertions = PyprojectAssertions(test_env)
        (
            fresh_assertions
            .has_workflow("test_hash")
            .has_model_with_filename("model.safetensors")
            .has_criticality("required")
        )

    def test_update_all_importance_levels(self, test_env, test_workspace):
        """Test cycling through all importance levels."""
        # ARRANGE
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model("model.safetensors", "checkpoints")
        model_builder.index_all()

        workflow = make_minimal_workflow("model.safetensors")
        simulate_comfyui_save_workflow(test_env, "test_levels", workflow)

        test_env.resolve_workflow(
            name="test_levels",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # ACT & ASSERT: Cycle through all levels
        for level in ["required", "flexible", "optional"]:
            success = test_env.workflow_manager.update_model_criticality(
                workflow_name="test_levels",
                model_identifier="model.safetensors",
                new_criticality=level
            )
            assert success

            assertions = PyprojectAssertions(test_env)
            (
                assertions
                .has_workflow("test_levels")
                .has_model_with_filename("model.safetensors")
                .has_criticality(level)
            )

    def test_update_unresolved_model(self, test_env, test_workspace):
        """Test that unresolved models can also have their importance updated."""
        # ARRANGE: Workflow with missing model
        workflow = make_minimal_workflow("missing.safetensors")
        simulate_comfyui_save_workflow(test_env, "unresolved", workflow)

        test_env.resolve_workflow(
            name="unresolved",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # Verify unresolved state
        assertions = PyprojectAssertions(test_env)
        (
            assertions
            .has_workflow("unresolved")
            .has_model_with_filename("missing.safetensors")
            .has_status("unresolved")
        )

        # ACT: Update importance
        success = test_env.workflow_manager.update_model_criticality(
            workflow_name="unresolved",
            model_identifier="missing.safetensors",
            new_criticality="optional"
        )

        # ASSERT: Should work for unresolved models too
        assert success

        fresh_assertions = PyprojectAssertions(test_env)
        (
            fresh_assertions
            .has_workflow("unresolved")
            .has_model_with_filename("missing.safetensors")
            .has_status("unresolved")
            .has_criticality("optional")
        )

    def test_model_not_found_returns_false(self, test_env, test_workspace):
        """Test that updating non-existent model returns False."""
        # ARRANGE
        workflow = make_minimal_workflow("model.safetensors")
        simulate_comfyui_save_workflow(test_env, "empty", workflow)

        # ACT
        success = test_env.workflow_manager.update_model_criticality(
            workflow_name="empty",
            model_identifier="nonexistent.safetensors",
            new_criticality="optional"
        )

        # ASSERT
        assert not success, "Should return False when model not found"

    def test_invalid_criticality_raises_error(self, test_env, test_workspace):
        """Test that invalid criticality values are rejected."""
        # ARRANGE
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

        # ACT & ASSERT
        with pytest.raises(ValueError, match="Invalid criticality"):
            test_env.workflow_manager.update_model_criticality(
                workflow_name="test_invalid",
                model_identifier="model.safetensors",
                new_criticality="super_important"
            )


class TestWorkflowModelManualCommands:
    """Test CLI handlers for manually declared workflow model dependencies."""

    def _commands_for_env(self, test_env):
        workspace = Mock()
        workspace.get_active_environment.return_value = test_env

        commands = EnvironmentCommands()
        commands.__dict__["workspace"] = workspace
        return commands

    def test_add_list_and_remove_manual_model_dependency(self, test_env, test_workspace, capsys):
        model_builder = ModelIndexBuilder(test_workspace)
        model_builder.add_model("custom_loader_model.safetensors", "diffusion_models")
        model_builder.index_all()

        commands = self._commands_for_env(test_env)
        add_args = argparse.Namespace(
            target_env=None,
            workflow_name="custom_loader_workflow",
            model_hash=None,
            relative_path="diffusion_models/custom_loader_model.safetensors",
            importance="required",
        )

        commands.workflow_model_add(add_args)
        add_output = capsys.readouterr().out
        assert "Added manual model dependency" in add_output

        models = test_env.pyproject.workflows.get_workflow_models("custom_loader_workflow")
        assert len(models) == 1
        assert models[0].filename == "custom_loader_model.safetensors"
        assert models[0].criticality == "required"
        assert models[0].declared_by == "manual"
        assert models[0].nodes == []

        list_args = argparse.Namespace(target_env=None, workflow_name="custom_loader_workflow")
        commands.workflow_model_list(list_args)
        list_output = capsys.readouterr().out
        assert "custom_loader_model.safetensors" in list_output
        assert "declared:   manual" in list_output

        remove_args = argparse.Namespace(
            target_env=None,
            workflow_name="custom_loader_workflow",
            model_hash=None,
            relative_path="diffusion_models/custom_loader_model.safetensors",
        )

        commands.workflow_model_remove(remove_args)
        remove_output = capsys.readouterr().out
        assert "Removed manual model dependency" in remove_output
        assert test_env.pyproject.workflows.get_workflow_models("custom_loader_workflow") == []
