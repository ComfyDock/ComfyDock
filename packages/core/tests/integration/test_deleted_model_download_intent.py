"""Integration test for deleted model handling.

When a previously resolved model is deleted from disk, the workflow resolver
should mark it as unresolved, NOT create a download intent. This gives users
a clean slate to re-resolve (move model back, find new URL, etc.).

The global table entry gets cleaned up by cleanup_orphans() during apply_resolution().
"""
from comfygit_core.strategies.auto import AutoModelStrategy, AutoNodeStrategy
from conftest import simulate_comfyui_save_workflow
from helpers.model_index_builder import ModelIndexBuilder
from helpers.pyproject_assertions import PyprojectAssertions


class TestDeletedModelResolution:
    """Test that deleted models are marked as unresolved, not download intents."""

    def test_deleted_model_becomes_unresolved(self, test_env, test_workspace):
        """Should mark as unresolved when resolved model is deleted from disk.

        Flow:
        1. Setup: Create model, index it, resolve workflow
        2. Delete model file from disk
        3. Sync model index (removes from SQLite)
        4. Re-resolve workflow
        5. Should be in models_unresolved (not download_intent)
        """
        # ARRANGE: Create model and index it
        models_dir = test_workspace.workspace_config_manager.get_models_directory()
        builder = ModelIndexBuilder(test_workspace)

        builder.add_model(
            filename="test_vae.safetensors",
            relative_path="vae",
            size_mb=2
        )
        builder.index_all()
        model_hash = builder.get_hash("test_vae.safetensors")

        # Add source to repository AND global table (simulating completed download)
        test_env.model_repository.add_source(
            model_hash,
            source_type="direct",
            source_url="https://example.com/models/test_vae.safetensors"
        )

        from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel
        from comfygit_core.models.workflow import WorkflowNodeWidgetRef

        global_model = ManifestModel(
            hash=model_hash,
            filename="test_vae.safetensors",
            size=2097183,
            relative_path="vae/test_vae.safetensors",
            category="vae",
            sources=["https://example.com/models/test_vae.safetensors"]
        )
        test_env.pyproject.models.add_model(global_model)

        # Create workflow with VAE loader
        workflow_json = {
            "id": "test-deleted-model",
            "revision": 0,
            "last_node_id": 1,
            "last_link_id": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "VAELoader",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["test_vae.safetensors"]
                }
            ],
            "links": [],
            "config": {},
            "version": 0.4
        }

        simulate_comfyui_save_workflow(test_env, "deleted_model_test", workflow_json)

        # Add per-workflow model entry to simulate previous resolution
        workflow_model = ManifestWorkflowModel(
            hash=model_hash,
            filename="test_vae.safetensors",
            category="vae",
            criticality="flexible",
            status="resolved",
            nodes=[WorkflowNodeWidgetRef(node_id="1", node_type="VAELoader", widget_index=0, widget_value="test_vae.safetensors")]
        )
        test_env.pyproject.workflows.add_workflow_model("deleted_model_test", workflow_model)

        # Verify model is in global table with sources
        assertions = PyprojectAssertions(test_env)
        (
            assertions
            .has_global_model(model_hash)
            .has_filename("test_vae.safetensors")
            .has_relative_path("vae/test_vae.safetensors")
        )

        # ACT 1: Delete model file
        model_path = models_dir / "vae" / "test_vae.safetensors"
        model_path.unlink()

        # ACT 2: Sync model index (removes model from SQLite)
        changes = test_workspace.sync_model_directory()
        assert changes == 1, f"Should detect 1 removal, got {changes} changes"

        # Verify model is gone from SQLite index
        models_in_index = test_env.model_repository.find_by_filename("test_vae.safetensors")
        assert len(models_in_index) == 0, "Model should be removed from index after sync"

        # ACT 3: Re-resolve workflow - should mark as unresolved
        resolution = test_env.resolve_workflow(
            name="deleted_model_test",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # ASSERT: Should be in unresolved, NOT create download intent
        vae_resolved = [
            m for m in resolution.models_resolved
            if "test_vae" in m.reference.widget_value
        ]
        vae_unresolved = [
            m for m in resolution.models_unresolved
            if "test_vae" in m.widget_value
        ]

        assert len(vae_unresolved) == 1, \
            "Deleted model should be in unresolved list"
        assert len(vae_resolved) == 0, \
            "Deleted model should NOT create download_intent even if global table has sources"

    def test_deleted_model_cleanup_on_apply(self, test_env, test_workspace):
        """Global table entry should be cleaned up when apply_resolution runs.

        This tests the full flow: delete model → re-resolve → apply → verify cleanup.
        """
        # ARRANGE: Create model and index it
        models_dir = test_workspace.workspace_config_manager.get_models_directory()
        builder = ModelIndexBuilder(test_workspace)

        builder.add_model(
            filename="cleanup_vae.safetensors",
            relative_path="vae",
            size_mb=2
        )
        builder.index_all()
        model_hash = builder.get_hash("cleanup_vae.safetensors")

        from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel
        from comfygit_core.models.workflow import WorkflowNodeWidgetRef

        # Add to global table with sources
        global_model = ManifestModel(
            hash=model_hash,
            filename="cleanup_vae.safetensors",
            size=2097183,
            relative_path="vae/cleanup_vae.safetensors",
            category="vae",
            sources=["https://example.com/models/cleanup_vae.safetensors"]
        )
        test_env.pyproject.models.add_model(global_model)

        # Create workflow
        workflow_json = {
            "id": "cleanup-test",
            "revision": 0,
            "last_node_id": 1,
            "last_link_id": 0,
            "nodes": [
                {
                    "id": 1,
                    "type": "VAELoader",
                    "flags": {},
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": ["cleanup_vae.safetensors"]
                }
            ],
            "links": [],
            "config": {},
            "version": 0.4
        }
        simulate_comfyui_save_workflow(test_env, "cleanup_test", workflow_json)

        # Add per-workflow model entry (resolved)
        workflow_model = ManifestWorkflowModel(
            hash=model_hash,
            filename="cleanup_vae.safetensors",
            category="vae",
            criticality="flexible",
            status="resolved",
            nodes=[WorkflowNodeWidgetRef(node_id="1", node_type="VAELoader", widget_index=0, widget_value="cleanup_vae.safetensors")]
        )
        test_env.pyproject.workflows.add_workflow_model("cleanup_test", workflow_model)

        # Verify global table has the entry
        assertions = PyprojectAssertions(test_env)
        assertions.has_global_model(model_hash)

        # ACT: Delete model and sync
        model_path = models_dir / "vae" / "cleanup_vae.safetensors"
        model_path.unlink()
        test_workspace.sync_model_directory()

        # Re-resolve
        resolution = test_env.resolve_workflow(
            name="cleanup_test",
            node_strategy=AutoNodeStrategy(),
            model_strategy=AutoModelStrategy()
        )

        # Apply resolution (this triggers cleanup_orphans)
        test_env.workflow_manager.apply_resolution(resolution)

        # ASSERT: Global table entry should be removed
        config = test_env.pyproject.load()
        global_models = config.get("tool", {}).get("comfygit", {}).get("models", {})
        assert model_hash not in global_models, \
            "Global table entry should be cleaned up after apply_resolution"

        # Workflow model should now be unresolved
        workflow_models = test_env.pyproject.workflows.get_workflow_models("cleanup_test")
        vae_model = next((m for m in workflow_models if m.filename == "cleanup_vae.safetensors"), None)
        assert vae_model is not None, "Workflow should still have model entry"
        assert vae_model.status == "unresolved", "Model status should be unresolved"
        assert vae_model.hash is None, "Model should not have hash after cleanup"
