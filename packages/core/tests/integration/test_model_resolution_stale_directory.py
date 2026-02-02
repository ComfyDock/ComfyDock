"""Integration test for workflow model resolution with stale directory references.

This test replicates a critical bug where:
1. User indexes models in directory A
2. User switches global models directory to B (which doesn't have all models)
3. User imports workflow requiring model from directory A
4. Resolution incorrectly reports model as "resolved" even though it's not accessible
5. ComfyUI fails at runtime because model isn't in current directory
"""



class TestWorkflowModelResolutionWithDirectorySwitch:
    """Test that model resolution correctly handles directory switches."""

    def test_model_resolution_fails_when_model_only_in_old_directory(self, test_workspace, test_env):
        """Regression test: verify model resolution correctly handles directory switches.

        Scenario:
        1. Create directory A with model v1-5-pruned.safetensors
        2. Index directory A (model gets hash, stored in index)
        3. Switch to directory B (doesn't have v1-5-pruned)
        4. Import workflow requiring v1-5-pruned
        5. VERIFY FIX: Resolution correctly marks model as "unresolved"
        6. Model from old directory is not visible, user can download/copy to new directory

        This prevents a critical bug where workflows would fail at runtime because
        ComfyUI symlinks to the current global directory only.
        """
        from conftest import simulate_comfyui_save_workflow
        from helpers.workflow_builder import make_minimal_workflow

        # ARRANGE: Create first models directory with checkpoint
        models_dir_old = test_workspace.paths.root / "old_models"
        models_dir_old.mkdir()
        (models_dir_old / "checkpoints").mkdir()

        # Create the model file
        model_filename = "v1-5-pruned-emaonly-fp16.safetensors"
        model_path = models_dir_old / "checkpoints" / model_filename
        model_content = b"V15_CHECKPOINT" + b"\x00" * (2 * 1024 * 1024)  # 2MB model
        model_path.write_bytes(model_content)

        # Set and index old directory
        test_workspace.set_models_directory(models_dir_old)

        # Verify model is indexed
        models = test_workspace.model_repository.find_by_filename(model_filename)
        assert len(models) == 1, "Model should be indexed in old directory"
        model_hash = models[0].hash

        # ACT: Switch to NEW global models directory (empty, no v1-5 model)
        models_dir_new = test_workspace.paths.root / "new_models"
        models_dir_new.mkdir()
        (models_dir_new / "checkpoints").mkdir()

        # Add a different model to new directory to make it non-empty
        other_model_path = models_dir_new / "checkpoints" / "some-other-model.safetensors"
        other_model_path.write_bytes(b"OTHER" + b"\x00" * (1 * 1024 * 1024))

        test_workspace.set_models_directory(models_dir_new)

        # Verify new directory is active and doesn't have v1-5
        current_dir = test_workspace.get_models_directory()
        assert current_dir == models_dir_new.resolve()

        # VERIFY FIX: current_directory should now be properly set after set_models_directory
        assert test_workspace.model_repository.current_directory == models_dir_new.resolve(), (
            "Fix verification: current_directory should be set to new directory"
        )

        # VERIFY FIX: Queries should now be filtered to current directory only
        models_in_current = test_workspace.model_repository.find_by_filename(model_filename)
        print(f"\nFIX VERIFIED: current_directory={test_workspace.model_repository.current_directory}")
        print(f"Models found in current directory: {len(models_in_current)}")
        print(f"  Current global dir: {models_dir_new.resolve()}")

        assert len(models_in_current) == 0, (
            "FIX: find_by_filename should only return models from current directory (new_models), not old_models"
        )

        # But model still exists in index with old location preserved
        all_locations = test_workspace.model_repository.get_locations(model_hash)
        assert len(all_locations) == 1, "Old location should still be tracked"
        assert all_locations[0]['base_directory'] == str(models_dir_old.resolve())

        # Create workflow that requires the v1-5 model
        workflow_json = make_minimal_workflow(model_filename)

        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow_json)

        # ASSERT: Resolution should detect that model is NOT available in current directory

        # Analyze workflow
        dependencies = test_env.workflow_manager.analyze_workflow("test_workflow")
        assert len(dependencies.found_models) == 1
        model_ref = dependencies.found_models[0]
        assert model_ref.widget_value == model_filename

        # Resolve workflow
        resolution = test_env.workflow_manager.resolve_workflow(dependencies)

        # DEBUG: Print what we found
        print("\n=== RESOLUTION RESULTS ===")
        print(f"Models resolved: {len(resolution.models_resolved)}")
        print(f"Models unresolved: {len(resolution.models_unresolved)}")
        print(f"Models ambiguous: {len(resolution.models_ambiguous)}")

        if resolution.models_resolved:
            for r in resolution.models_resolved:
                print(f"  Resolved: {r.reference.widget_value}")
                if r.resolved_model:
                    print(f"    - base_directory: {r.resolved_model.base_directory}")
                    print(f"    - relative_path: {r.resolved_model.relative_path}")

        if resolution.models_unresolved:
            for r in resolution.models_unresolved:
                print(f"  Unresolved: {r.widget_value}")

        # VERIFY FIX: With current_directory properly set, resolution should detect
        # that model is not available in current directory

        # The fix prevents the bug by:
        # - current_directory is set during set_models_directory() and sync_model_directory()
        # - ModelRepository queries filter by current_directory
        # - Resolver only sees models from current directory
        # - Model from old_models is not found, marked as unresolved

        # EXPECTED BEHAVIOR: Model should be unresolved
        assert len(resolution.models_unresolved) == 1, (
            f"Model should be UNRESOLVED since it's not in current global directory. "
            f"Found {len(resolution.models_unresolved)} unresolved, {len(resolution.models_resolved)} resolved"
        )
        assert resolution.models_unresolved[0].widget_value == model_filename
        assert len(resolution.models_resolved) == 0, (
            "No models should be marked as resolved - model only exists in old directory"
        )
