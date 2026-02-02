"""Integration test for workflow cache invalidation when models are deleted.

This test reproduces the bug where workflow caches are not invalidated when
the model index changes due to model deletion, causing stale resolutions.
"""
from comfygit_core.strategies.auto import AutoModelStrategy, AutoNodeStrategy
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder


class TestWorkflowCacheInvalidationOnModelDeletion:
    """Test that workflow cache invalidates when models are deleted from index."""

    def test_cache_invalidates_after_model_deletion(self, test_env, test_workspace):
        """Cache should invalidate when models are deleted and index is synced.

        Reproduces bug: After deleting model files and running 'model index sync',
        the workflow cache still returns stale resolution showing models as found.
        """
        # ARRANGE: Create models in the index
        models_dir = test_workspace.workspace_config_manager.get_models_directory()
        builder = ModelIndexBuilder(test_workspace)

        # Add model referenced by workflow
        builder.add_model(
            filename="test_checkpoint.safetensors",
            relative_path="checkpoints",
            size_mb=4
        )
        builder.index_all()

        # Create simple workflow with checkpoint
        workflow_json = {
            "id": "cache-test",
            "revision": 0,
            "last_node_id": 1,
            "last_link_id": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "CheckpointLoaderSimple",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["test_checkpoint.safetensors"]
                }
            ],
            "links": [],
            "config": {},
            "version": 0.4
        }

        simulate_comfyui_save_workflow(test_env, "cache_test", workflow_json)

        # ACT 1: First resolution - should find model (populates cache)
        resolution1 = test_env.resolve_workflow(
            name="cache_test",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # ASSERT: Model should be resolved initially
        checkpoint_resolved_1 = [
            m for m in resolution1.models_resolved
            if "test_checkpoint" in m.reference.widget_value
        ]
        assert len(checkpoint_resolved_1) == 1, "Model should be resolved initially"

        # Store pyproject mtime to verify it doesn't change
        pyproject_mtime_before = test_env.pyproject_path.stat().st_mtime

        # ACT 2: Delete model file
        model_path = models_dir / "checkpoints" / "test_checkpoint.safetensors"
        model_path.unlink()

        # ACT 3: Sync model index (removes model from SQLite)
        changes = test_workspace.sync_model_directory()

        # Verify model is gone from index
        model_repo = test_env.model_repository
        models_in_index = model_repo.find_by_filename("test_checkpoint.safetensors")
        assert len(models_in_index) == 0, "Model should be removed from index after sync"
        assert changes == 1, f"Should detect 1 removal, got {changes} changes"

        # Verify pyproject.toml was NOT modified
        pyproject_mtime_after = test_env.pyproject_path.stat().st_mtime
        assert pyproject_mtime_before == pyproject_mtime_after, \
            "Pyproject.toml should NOT change when model is deleted"

        # ACT 4: Second resolution - should detect model is missing
        resolution2 = test_env.resolve_workflow(
            name="cache_test",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # ASSERT: Cache should be invalidated, model should now be unresolved
        checkpoint_resolved_2 = [
            m for m in resolution2.models_resolved
            if "test_checkpoint" in m.reference.widget_value
        ]
        checkpoint_unresolved_2 = [
            m for m in resolution2.models_unresolved
            if "test_checkpoint" in m.widget_value
        ]

        # This is the key assertion that demonstrates the bug
        assert len(checkpoint_resolved_2) == 0, \
            "BUG: Model should NOT be resolved after deletion (cache not invalidated!)"
        assert len(checkpoint_unresolved_2) == 1, \
            "Model should be in unresolved list after deletion"

    def test_cache_preserved_when_no_model_changes(self, test_env, test_workspace):
        """Cache should NOT invalidate when model index is synced with no changes."""
        # ARRANGE: Create model
        builder = ModelIndexBuilder(test_workspace)
        builder.add_model(
            filename="stable_model.safetensors",
            relative_path="checkpoints",
            size_mb=4
        )
        builder.index_all()

        # Create workflow
        workflow_json = {
            "id": "stable-test",
            "revision": 0,
            "last_node_id": 1,
            "last_link_id": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "CheckpointLoaderSimple",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["stable_model.safetensors"]
                }
            ],
            "links": [],
            "config": {},
            "version": 0.4
        }

        simulate_comfyui_save_workflow(test_env, "stable_test", workflow_json)

        # ACT 1: First resolution (populates cache)
        resolution1 = test_env.resolve_workflow(
            name="stable_test",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # ACT 2: Sync again with no changes
        changes = test_workspace.sync_model_directory()

        # ACT 3: Second resolution (should use cache)
        resolution2 = test_env.resolve_workflow(
            name="stable_test",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # ASSERT: No changes detected, both resolutions should be identical
        assert changes == 0, "Should detect no changes during second sync"
        assert len(resolution1.models_resolved) == len(resolution2.models_resolved), \
            "Cache should be preserved when no changes occur"
