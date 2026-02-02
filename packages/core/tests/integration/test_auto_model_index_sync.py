"""Integration tests for automatic model index syncing during workflow resolution."""

import os
from pathlib import Path


def _bump_mtime(path: Path, seconds: float = 2.0) -> None:
    """Bump mtime deterministically to avoid sleep-based flakiness."""
    current = path.stat().st_mtime
    new_mtime = current + seconds
    os.utime(path, (new_mtime, new_mtime))


class TestAutoModelIndexSync:
    """Test automatic model index synchronization when models directory changes."""

    def test_workflow_resolve_auto_syncs_when_model_added_after_initial_scan(
        self, test_env, test_workspace, workflow_fixtures
    ):
        """Test that workflow resolution auto-syncs the index when new models are added.

        Scenario:
        1. Initial model scan (creates baseline index)
        2. User adds new model file to models directory
        3. User runs workflow resolve that needs that model
        4. System should automatically detect stale index and sync before resolving
        5. Model should be found and resolved correctly

        This test verifies the UX problem is solved: users don't need to manually
        run 'model index sync' after copying model files.
        """
        from conftest import simulate_comfyui_save_workflow
        from helpers.workflow_builder import make_minimal_workflow

        models_dir = test_workspace.workspace_config_manager.get_models_directory()

        # ARRANGE: Initial state - empty model index
        test_workspace.sync_model_directory()  # Creates baseline

        # Bump mtime deterministically after sync
        _bump_mtime(models_dir)

        # Create checkpoint directory
        checkpoints_dir = models_dir / "checkpoints"
        checkpoints_dir.mkdir(parents=True, exist_ok=True)

        # Add new model file AFTER initial sync (simulates user copying file)
        model_filename = "test_checkpoint_v1.safetensors"
        model_path = checkpoints_dir / model_filename

        # Create 4MB stub model with deterministic content
        content = b"TEST_MODEL_" + model_filename.encode() + b"\x00" * (4 * 1024 * 1024)
        model_path.write_bytes(content)

        # Verify model is NOT in index yet (stale state)
        results_before = test_workspace.model_repository.find_by_filename(model_filename)
        assert len(results_before) == 0, "Model should not be in index before auto-sync"

        # Create workflow that references the new model
        workflow = make_minimal_workflow(checkpoint_file=model_filename)
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # ACT: Resolve workflow (should trigger auto-sync via workspace.get_environment)
        # Use workspace.get_environment with auto_sync=True to trigger sync
        env_with_sync = test_workspace.get_environment("test-env", auto_sync=True)
        resolution = env_with_sync.resolve_workflow("test_workflow", fix=False)

        # ASSERT: Model should be found and resolved (auto-sync worked!)
        assert len(resolution.models_resolved) == 1, (
            "Model should be resolved after auto-sync. "
            "If this fails, auto-sync is not working during workflow resolution."
        )
        assert resolution.models_resolved[0].resolved_model is not None
        assert model_filename in resolution.models_resolved[0].resolved_model.filename

        # Verify model is now in index
        results_after = test_workspace.model_repository.find_by_filename(model_filename)
        assert len(results_after) == 1, "Model should be in index after auto-sync"

    def test_workflow_resolve_with_existing_models(
        self, test_env, test_workspace, test_models, workflow_fixtures
    ):
        """Test that workflow resolution works correctly with existing indexed models.

        For MVP: auto_sync always runs but is fast due to mtime optimization.
        This test verifies that existing models are resolved correctly.
        """
        from conftest import simulate_comfyui_save_workflow
        from helpers.workflow_builder import make_minimal_workflow

        # ARRANGE: Use existing test_models fixture (already synced)
        # Get a model from the fixture
        model_filename = list(test_models.keys())[0]  # Use first available model
        assert model_filename in test_models, "Test model should exist"

        # Create workflow referencing existing model
        workflow = make_minimal_workflow(checkpoint_file=model_filename)
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # ACT: Resolve workflow (auto-sync will run but skip unchanged files via mtime)
        env_with_sync = test_workspace.get_environment("test-env", auto_sync=True)
        resolution = env_with_sync.resolve_workflow("test_workflow", fix=False)

        # ASSERT: Model should be resolved correctly
        assert len(resolution.models_resolved) == 1
        assert model_filename in resolution.models_resolved[0].resolved_model.filename

    def test_auto_sync_handles_new_model_in_new_directory(
        self, test_env, test_workspace, workflow_fixtures
    ):
        """Test that auto-sync correctly indexes models added in new subdirectories.

        This test verifies that creating a new directory with models triggers
        proper indexing during auto-sync.
        """
        from conftest import simulate_comfyui_save_workflow
        from helpers.workflow_builder import make_minimal_workflow

        models_dir = test_workspace.workspace_config_manager.get_models_directory()

        # ARRANGE: Initial sync
        test_workspace.sync_model_directory()

        # Bump mtime deterministically after sync
        _bump_mtime(models_dir)

        # Create new subdirectory
        loras_dir = models_dir / "loras"
        loras_dir.mkdir(parents=True, exist_ok=True)

        # Add model in new directory
        model_filename = "style_lora_v1.safetensors"
        model_path = loras_dir / model_filename
        content = b"TEST_LORA_" + model_filename.encode() + b"\x00" * (2 * 1024 * 1024)
        model_path.write_bytes(content)

        # Verify model is NOT in index yet
        results_before = test_workspace.model_repository.find_by_filename(model_filename)
        assert len(results_before) == 0, "Model should not be in index before sync"

        # Create workflow referencing the model
        workflow = make_minimal_workflow(checkpoint_file=model_filename)
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        # ACT: Resolve workflow to trigger auto-sync
        env_with_sync = test_workspace.get_environment("test-env", auto_sync=True)
        env_with_sync.resolve_workflow("test_workflow", fix=False)

        # ASSERT: Model should be indexed after auto-sync
        results_after = test_workspace.model_repository.find_by_filename(model_filename)
        assert len(results_after) == 1, "Model should be in index after auto-sync"

    def test_auto_sync_handles_model_deletion(
        self, test_env, test_workspace, workflow_fixtures
    ):
        """Test that auto-sync cleans up deleted model entries from index.

        When a model file is deleted, the directory mtime changes, triggering
        a sync that removes the stale entry from the index.
        """
        from conftest import simulate_comfyui_save_workflow
        from helpers.workflow_builder import make_minimal_workflow

        models_dir = test_workspace.workspace_config_manager.get_models_directory()
        checkpoints_dir = models_dir / "checkpoints"
        checkpoints_dir.mkdir(parents=True, exist_ok=True)

        # ARRANGE: Add model and sync
        model_filename = "temporary_model.safetensors"
        model_path = checkpoints_dir / model_filename
        content = b"TEST_MODEL_" + model_filename.encode() + b"\x00" * (4 * 1024 * 1024)
        model_path.write_bytes(content)

        test_workspace.sync_model_directory()

        # Verify model is in index
        results_before = test_workspace.model_repository.find_by_filename(model_filename)
        assert len(results_before) == 1, "Model should be in index"

        # Bump mtime deterministically after sync
        _bump_mtime(models_dir)

        # Delete the model file (changes directory mtime)
        model_path.unlink()

        # ACT: Trigger auto-sync via workflow resolution
        # (workflow will fail to resolve, but index should be cleaned up)
        workflow = make_minimal_workflow(checkpoint_file="some_other_model.safetensors")
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        env_with_sync = test_workspace.get_environment("test-env", auto_sync=True)
        env_with_sync.resolve_workflow("test_workflow", fix=False)

        # ASSERT: Deleted model should be removed from index
        results_after = test_workspace.model_repository.find_by_filename(model_filename)
        assert len(results_after) == 0, (
            "Deleted model should be removed from index after auto-sync"
        )

    def test_auto_sync_works_cross_platform(
        self, test_env, test_workspace, workflow_fixtures
    ):
        """Test that auto-sync works on different platforms (Linux, macOS, Windows).

        This test verifies that directory mtime detection works consistently
        across platforms by using Path.stat() which is cross-platform.
        """
        from conftest import simulate_comfyui_save_workflow
        from helpers.workflow_builder import make_minimal_workflow

        models_dir = test_workspace.workspace_config_manager.get_models_directory()

        # ARRANGE: Initial sync
        test_workspace.sync_model_directory()
        initial_config = test_workspace.workspace_config_manager.load()
        initial_sync_time = initial_config.global_model_directory.last_sync

        # Bump mtime deterministically after sync
        _bump_mtime(models_dir)

        # Add model (should work on all platforms)
        checkpoints_dir = models_dir / "checkpoints"
        checkpoints_dir.mkdir(parents=True, exist_ok=True)

        model_filename = "cross_platform_test.safetensors"
        model_path = checkpoints_dir / model_filename
        content = b"TEST_" + model_filename.encode() + b"\x00" * (1 * 1024 * 1024)
        model_path.write_bytes(content)

        # Verify directory mtime changed (cross-platform check)
        dir_stat = checkpoints_dir.stat()
        from datetime import datetime
        dir_mtime = datetime.fromisoformat(initial_sync_time).timestamp()

        # Directory mtime should be newer than last sync
        assert dir_stat.st_mtime > dir_mtime, (
            "Directory mtime should change when file is added (cross-platform behavior)"
        )

        # ACT: Trigger auto-sync
        workflow = make_minimal_workflow(checkpoint_file=model_filename)
        simulate_comfyui_save_workflow(test_env, "test_workflow", workflow)

        env_with_sync = test_workspace.get_environment("test-env", auto_sync=True)
        resolution = env_with_sync.resolve_workflow("test_workflow", fix=False)

        # ASSERT: Model should be resolved (cross-platform sync worked)
        assert len(resolution.models_resolved) == 1
        assert model_filename in resolution.models_resolved[0].resolved_model.filename
